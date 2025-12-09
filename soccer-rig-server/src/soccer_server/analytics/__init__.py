"""
Video analytics pipeline for soccer footage.

Handles:
- Player detection and tracking
- Ball detection and tracking
- Action/event classification
- Event logging to database
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum
import json
import threading
import queue

logger = logging.getLogger(__name__)


@dataclass
class Detection:
    """A single detection in a frame."""
    class_name: str
    confidence: float
    bbox: Tuple[int, int, int, int]  # x, y, w, h
    track_id: Optional[int] = None


@dataclass
class FrameAnalysis:
    """Analysis results for a single frame."""
    frame_number: int
    timestamp_sec: float
    players: List[Detection]
    ball: Optional[Detection]
    actions: List[Dict[str, Any]]


class AnalysisPipeline:
    """
    Main video analysis pipeline.

    Processes video frames to detect players, ball, and actions,
    logging everything to the database.
    """

    def __init__(self, config, db_manager):
        """
        Initialize the analysis pipeline.

        Args:
            config: Analytics configuration
            db_manager: DatabaseManager instance
        """
        self.config = config
        self.db = db_manager

        # Models (loaded lazily)
        self._player_detector = None
        self._ball_detector = None
        self._action_classifier = None
        self._tracker = None

        # Processing queue
        self._job_queue = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False

        # Stats
        self._processed_frames = 0
        self._detected_events = 0

    def start(self) -> None:
        """Start the background analysis worker."""
        self._running = True
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        logger.info("Analytics pipeline started")

    def stop(self) -> None:
        """Stop the analysis worker."""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
        logger.info("Analytics pipeline stopped")

    def queue_analysis(self, game_id: int, video_path: str) -> str:
        """
        Queue a video for analysis.

        Returns:
            Job ID
        """
        job_id = f"analysis_{game_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self._job_queue.put({
            "job_id": job_id,
            "game_id": game_id,
            "video_path": video_path,
            "status": "queued",
            "queued_at": datetime.now(),
        })
        logger.info(f"Queued analysis job {job_id} for game {game_id}")
        return job_id

    def _worker_loop(self) -> None:
        """Background worker for processing analysis jobs."""
        while self._running:
            try:
                job = self._job_queue.get(timeout=1)
                self._process_job(job)
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Analysis worker error: {e}")

    def _process_job(self, job: Dict[str, Any]) -> None:
        """Process a single analysis job."""
        game_id = job["game_id"]
        video_path = job["video_path"]

        logger.info(f"Starting analysis for game {game_id}")

        try:
            # Load models if needed
            self._ensure_models_loaded()

            # Process video
            self._analyze_video(game_id, video_path)

            # Update game as analyzed
            game = self.db.get_game_by_id(game_id)
            if game:
                with self.db.get_session() as session:
                    game.is_analyzed = True
                    session.merge(game)
                    session.commit()

            logger.info(f"Analysis complete for game {game_id}")

        except Exception as e:
            logger.error(f"Analysis failed for game {game_id}: {e}")
            raise

    def _ensure_models_loaded(self) -> None:
        """Load ML models if not already loaded."""
        if self._player_detector is None:
            self._load_models()

    def _load_models(self) -> None:
        """Load detection and classification models."""
        logger.info("Loading ML models...")

        try:
            # Try to load YOLO for player detection
            from ultralytics import YOLO

            model_path = self.config.analytics.player_detection_model
            if Path(model_path).exists():
                self._player_detector = YOLO(model_path)
            else:
                # Fall back to pretrained model
                self._player_detector = YOLO("yolov8n.pt")

            logger.info("Player detection model loaded")

        except ImportError:
            logger.warning("ultralytics not installed, using placeholder detector")
            self._player_detector = PlaceholderDetector()

        # Action classifier (placeholder for now)
        self._action_classifier = ActionClassifier(self.config)

        logger.info("ML models loaded")

    def _analyze_video(self, game_id: int, video_path: str) -> None:
        """Analyze a video file frame by frame."""
        import cv2

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        # Sample rate - process every N frames
        sample_rate = int(fps / self.config.analytics.detection_fps)

        # Player tracking state
        player_tracks: Dict[int, List[Dict]] = {}

        frame_number = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Only process sampled frames
            if frame_number % sample_rate == 0:
                timestamp_sec = frame_number / fps

                # Run detection
                analysis = self._analyze_frame(frame, frame_number, timestamp_sec)

                # Log tracks to database
                self._log_tracks(game_id, analysis, player_tracks)

                # Detect and log events
                events = self._detect_events(analysis, player_tracks)
                for event in events:
                    self._log_event(game_id, event)

                self._processed_frames += 1

                # Progress logging
                if frame_number % (sample_rate * 100) == 0:
                    progress = (frame_number / total_frames) * 100
                    logger.info(f"Analysis progress: {progress:.1f}%")

            frame_number += 1

        cap.release()

        # Finalize - calculate player stats
        self._finalize_analysis(game_id)

    def _analyze_frame(
        self,
        frame,
        frame_number: int,
        timestamp_sec: float
    ) -> FrameAnalysis:
        """Analyze a single frame."""
        players = []
        ball = None

        # Run player detection
        if self._player_detector:
            detections = self._run_detection(frame)
            for det in detections:
                if det.class_name == "person":
                    players.append(det)
                elif det.class_name == "sports ball":
                    ball = det

        # Run action classification
        actions = []
        if self._action_classifier and players:
            actions = self._action_classifier.classify(frame, players, ball)

        return FrameAnalysis(
            frame_number=frame_number,
            timestamp_sec=timestamp_sec,
            players=players,
            ball=ball,
            actions=actions,
        )

    def _run_detection(self, frame) -> List[Detection]:
        """Run object detection on a frame."""
        detections = []

        if hasattr(self._player_detector, 'predict'):
            # YOLO detection
            results = self._player_detector.predict(
                frame,
                conf=self.config.analytics.detection_confidence,
                verbose=False,
            )

            for result in results:
                for box in result.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    cls_id = int(box.cls[0])
                    conf = float(box.conf[0])
                    class_name = result.names[cls_id]
                    track_id = int(box.id[0]) if box.id is not None else None

                    detections.append(Detection(
                        class_name=class_name,
                        confidence=conf,
                        bbox=(int(x1), int(y1), int(x2 - x1), int(y2 - y1)),
                        track_id=track_id,
                    ))

        return detections

    def _log_tracks(
        self,
        game_id: int,
        analysis: FrameAnalysis,
        player_tracks: Dict[int, List[Dict]]
    ) -> None:
        """Log player tracking data to database."""
        for player in analysis.players:
            if player.track_id is None:
                continue

            # Convert bbox to normalized field position
            # This is a simplified mapping - real implementation would need
            # camera calibration and homography
            x, y, w, h = player.bbox
            center_x = (x + w / 2)
            center_y = (y + h)  # Bottom of bbox = feet

            # Store in tracking dict for speed calculation
            if player.track_id not in player_tracks:
                player_tracks[player.track_id] = []

            player_tracks[player.track_id].append({
                "timestamp_sec": analysis.timestamp_sec,
                "x": center_x,
                "y": center_y,
                "bbox": player.bbox,
            })

            # Calculate speed if we have history
            speed_kmh = 0
            history = player_tracks[player.track_id]
            if len(history) >= 2:
                prev = history[-2]
                dt = analysis.timestamp_sec - prev["timestamp_sec"]
                if dt > 0:
                    dx = center_x - prev["x"]
                    dy = center_y - prev["y"]
                    # Simplified speed calc (would need proper scale)
                    pixel_dist = (dx**2 + dy**2) ** 0.5
                    speed_kmh = (pixel_dist / dt) * 0.01  # Rough conversion

            # Log to database (batched in production)
            self.db.log_track(
                game_id=game_id,
                timestamp_sec=analysis.timestamp_sec,
                x=center_x / 1920,  # Normalize to 0-1
                y=center_y / 1080,
                frame_number=analysis.frame_number,
                speed_kmh=speed_kmh,
                bbox_x=x,
                bbox_y=y,
                bbox_w=w,
                bbox_h=h,
                confidence=player.confidence,
            )

    def _detect_events(
        self,
        analysis: FrameAnalysis,
        player_tracks: Dict[int, List[Dict]]
    ) -> List[Dict[str, Any]]:
        """Detect events from frame analysis."""
        events = []

        # Use action classifier results
        for action in analysis.actions:
            events.append({
                "event_type": action["type"],
                "timestamp_sec": analysis.timestamp_sec,
                "frame_number": analysis.frame_number,
                "confidence": action.get("confidence", 1.0),
                "player_track_id": action.get("player_id"),
                "x": action.get("x"),
                "y": action.get("y"),
                "metadata": action.get("metadata", {}),
            })

        # Detect sprints from tracking data
        for track_id, history in player_tracks.items():
            if len(history) >= 5:
                recent = history[-5:]
                speeds = []
                for i in range(1, len(recent)):
                    dt = recent[i]["timestamp_sec"] - recent[i-1]["timestamp_sec"]
                    if dt > 0:
                        dx = recent[i]["x"] - recent[i-1]["x"]
                        dy = recent[i]["y"] - recent[i-1]["y"]
                        dist = (dx**2 + dy**2) ** 0.5
                        speeds.append(dist / dt)

                avg_speed = sum(speeds) / len(speeds) if speeds else 0
                # Sprint threshold (simplified)
                if avg_speed > 500:  # Arbitrary threshold
                    events.append({
                        "event_type": "sprint",
                        "timestamp_sec": analysis.timestamp_sec,
                        "frame_number": analysis.frame_number,
                        "confidence": 0.7,
                        "player_track_id": track_id,
                    })

        return events

    def _log_event(self, game_id: int, event: Dict[str, Any]) -> None:
        """Log an event to the database."""
        from soccer_server.database import EventType

        # Map string type to enum
        type_mapping = {
            "pass": EventType.PASS,
            "shot": EventType.SHOT,
            "dribble": EventType.DRIBBLE,
            "sprint": EventType.SPRINT,
            "tackle": EventType.TACKLE,
            "header": EventType.HEADER,
            "gk_save": EventType.GK_SAVE,
            "gk_punch": EventType.GK_PUNCH,
            "gk_catch": EventType.GK_CATCH,
            "gk_distribution": EventType.GK_DISTRIBUTION_THROW,
            "movement_off_ball": EventType.MOVEMENT_OFF_BALL,
        }

        event_type_str = event.get("event_type", "").lower()
        if event_type_str not in type_mapping:
            return  # Skip unknown event types

        self.db.log_event(
            game_id=game_id,
            event_type=type_mapping[event_type_str],
            timestamp_sec=event["timestamp_sec"],
            frame_number=event.get("frame_number"),
            confidence=event.get("confidence", 1.0),
            x=event.get("x"),
            y=event.get("y"),
            metadata_json=event.get("metadata"),
        )

        self._detected_events += 1

    def _finalize_analysis(self, game_id: int) -> None:
        """Finalize analysis - calculate aggregate stats."""
        logger.info(f"Finalizing analysis for game {game_id}")

        # Calculate player stats would go here
        # - Total distance covered
        # - Max speed
        # - Event counts
        # etc.

    def get_status(self) -> Dict[str, Any]:
        """Get pipeline status."""
        return {
            "running": self._running,
            "queued_jobs": self._job_queue.qsize(),
            "processed_frames": self._processed_frames,
            "detected_events": self._detected_events,
            "models_loaded": self._player_detector is not None,
        }


class PlaceholderDetector:
    """Placeholder detector when YOLO is not available."""

    def predict(self, frame, **kwargs):
        """Return empty results."""
        return []


class ActionClassifier:
    """
    Classifies player actions from video frames.

    Uses temporal context and pose estimation to identify:
    - Dribbling (player has ball, moving)
    - Passing (ball trajectory change)
    - Shooting (ball toward goal)
    - Tackling (two players intersecting)
    - Goalkeeper actions
    """

    def __init__(self, config):
        self.config = config
        self._model = None

    def classify(
        self,
        frame,
        players: List[Detection],
        ball: Optional[Detection]
    ) -> List[Dict[str, Any]]:
        """
        Classify actions in the current frame.

        Returns:
            List of detected actions
        """
        actions = []

        # Simple heuristics for now - would be ML model in production

        # Check for ball possession
        if ball:
            ball_x, ball_y, ball_w, ball_h = ball.bbox
            ball_center = (ball_x + ball_w / 2, ball_y + ball_h / 2)

            for player in players:
                px, py, pw, ph = player.bbox
                player_feet = (px + pw / 2, py + ph)

                # Distance from player feet to ball
                dist = ((ball_center[0] - player_feet[0])**2 +
                        (ball_center[1] - player_feet[1])**2) ** 0.5

                # If close to ball, might be dribbling
                if dist < 100:
                    actions.append({
                        "type": "dribble",
                        "confidence": max(0.3, 1.0 - dist / 100),
                        "player_id": player.track_id,
                        "x": player_feet[0] / 1920,
                        "y": player_feet[1] / 1080,
                    })

        # Detect goalkeeper actions based on position
        # (In real system, would track jersey numbers and positions)

        return actions


# =============================================================================
# Clip Generator
# =============================================================================

class ClipGenerator:
    """Generates video clips for specific events or player activities."""

    def __init__(self, config):
        self.config = config
        self.clips_path = Path(config.storage.clips_path)
        self.clips_path.mkdir(parents=True, exist_ok=True)

    def generate_event_clip(
        self,
        video_path: str,
        event_timestamp: float,
        duration_before: float = 5.0,
        duration_after: float = 5.0,
        output_name: Optional[str] = None,
    ) -> str:
        """
        Generate a clip around an event.

        Args:
            video_path: Source video path
            event_timestamp: Event timestamp in seconds
            duration_before: Seconds before event
            duration_after: Seconds after event
            output_name: Output filename (auto-generated if None)

        Returns:
            Path to generated clip
        """
        import subprocess

        start_time = max(0, event_timestamp - duration_before)
        duration = duration_before + duration_after

        if output_name is None:
            output_name = f"clip_{int(event_timestamp)}_{datetime.now().strftime('%H%M%S')}.mp4"

        output_path = self.clips_path / output_name

        cmd = [
            self.config.processing.ffmpeg_path,
            "-ss", str(start_time),
            "-i", video_path,
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-y",
            str(output_path),
        ]

        subprocess.run(cmd, check=True, capture_output=True)

        return str(output_path)

    def generate_player_highlight(
        self,
        video_path: str,
        events: List[Dict[str, Any]],
        output_name: Optional[str] = None,
        max_duration: float = 120.0,
    ) -> str:
        """
        Generate a highlight reel for a player.

        Args:
            video_path: Source video path
            events: List of events with timestamps
            output_name: Output filename
            max_duration: Maximum highlight duration

        Returns:
            Path to generated highlight
        """
        import subprocess
        import tempfile

        if not events:
            raise ValueError("No events provided")

        # Sort events by timestamp
        events = sorted(events, key=lambda e: e.get("timestamp_sec", 0))

        # Generate individual clips
        clips = []
        total_duration = 0

        for event in events:
            if total_duration >= max_duration:
                break

            timestamp = event.get("timestamp_sec", 0)
            clip_duration = 10.0  # 5s before + 5s after

            # Skip if too close to previous clip
            if clips and (timestamp - clips[-1]["end"]) < 3:
                continue

            clip_name = f"temp_clip_{len(clips)}.mp4"
            clip_path = self.clips_path / clip_name

            try:
                self.generate_event_clip(
                    video_path,
                    timestamp,
                    duration_before=5.0,
                    duration_after=5.0,
                    output_name=clip_name,
                )

                clips.append({
                    "path": str(clip_path),
                    "start": timestamp - 5,
                    "end": timestamp + 5,
                })

                total_duration += clip_duration

            except Exception as e:
                logger.warning(f"Failed to generate clip for event: {e}")

        if not clips:
            raise ValueError("Could not generate any clips")

        # Concatenate clips
        if output_name is None:
            output_name = f"highlight_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"

        output_path = self.clips_path / output_name

        # Create concat file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            for clip in clips:
                f.write(f"file '{clip['path']}'\n")
            concat_file = f.name

        try:
            cmd = [
                self.config.processing.ffmpeg_path,
                "-f", "concat",
                "-safe", "0",
                "-i", concat_file,
                "-c", "copy",
                "-y",
                str(output_path),
            ]

            subprocess.run(cmd, check=True, capture_output=True)

        finally:
            # Cleanup temp clips
            Path(concat_file).unlink(missing_ok=True)
            for clip in clips:
                Path(clip["path"]).unlink(missing_ok=True)

        return str(output_path)

    def generate_thumbnail(
        self,
        video_path: str,
        timestamp: float,
        output_name: Optional[str] = None,
    ) -> str:
        """Generate a thumbnail from a video frame."""
        import subprocess

        if output_name is None:
            output_name = f"thumb_{int(timestamp)}.jpg"

        output_path = self.clips_path / output_name

        cmd = [
            self.config.processing.ffmpeg_path,
            "-ss", str(timestamp),
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "2",
            "-y",
            str(output_path),
        ]

        subprocess.run(cmd, check=True, capture_output=True)

        return str(output_path)
