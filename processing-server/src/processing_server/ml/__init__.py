"""
ML Pipeline for Soccer Event Detection.

Uses YOLO for player/ball detection and pose estimation,
then applies rule-based event classification.
"""

import cv2
import numpy as np
import logging
import threading
import queue
import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from collections import deque

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Soccer event types."""
    # Ball events
    GOAL = "goal"
    SHOT = "shot"
    SHOT_ON_TARGET = "shot_on_target"
    PASS = "pass"
    CROSS = "cross"
    CORNER = "corner"
    FREE_KICK = "free_kick"
    THROW_IN = "throw_in"

    # Player events
    DRIBBLE = "dribble"
    TACKLE = "tackle"
    FOUL = "foul"
    OFFSIDE = "offside"

    # Goalkeeper events
    SAVE = "save"
    PUNCH = "punch"
    CATCH = "catch"
    DISTRIBUTION = "distribution"
    DIVE = "dive"

    # Game events
    KICKOFF = "kickoff"
    HALFTIME = "halftime"
    FULLTIME = "fulltime"
    HIGHLIGHT = "highlight"  # General exciting moment


@dataclass
class BoundingBox:
    """Object bounding box."""
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float
    class_id: int
    class_name: str

    @property
    def center(self) -> Tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    @property
    def area(self) -> float:
        return (self.x2 - self.x1) * (self.y2 - self.y1)


@dataclass
class PlayerDetection:
    """Detected player with optional pose."""
    bbox: BoundingBox
    track_id: Optional[int] = None
    team: Optional[str] = None  # Detected team based on jersey color
    is_goalkeeper: bool = False
    pose_keypoints: Optional[np.ndarray] = None  # 17 keypoints for pose
    velocity: Optional[Tuple[float, float]] = None


@dataclass
class BallDetection:
    """Detected ball."""
    bbox: BoundingBox
    track_id: Optional[int] = None
    velocity: Optional[Tuple[float, float]] = None
    is_in_play: bool = True


@dataclass
class FrameAnalysis:
    """Analysis results for a single frame."""
    frame_number: int
    timestamp_ms: float
    players: List[PlayerDetection] = field(default_factory=list)
    ball: Optional[BallDetection] = None
    field_lines: Optional[np.ndarray] = None  # Detected field markings


@dataclass
class GameEvent:
    """Detected game event."""
    event_type: EventType
    timestamp_ms: float
    frame_number: int
    confidence: float
    duration_ms: float = 0
    players_involved: List[int] = field(default_factory=list)  # Track IDs
    location: Optional[Tuple[float, float]] = None  # Field coordinates
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "event_type": self.event_type.value,
            "timestamp_ms": self.timestamp_ms,
            "frame_number": self.frame_number,
            "confidence": self.confidence,
            "duration_ms": self.duration_ms,
            "players_involved": self.players_involved,
            "location": self.location,
            "metadata": self.metadata,
        }


class ObjectTracker:
    """Simple object tracker using centroid tracking."""

    def __init__(self, max_disappeared: int = 30):
        self.next_id = 0
        self.objects: Dict[int, Tuple[float, float]] = {}
        self.disappeared: Dict[int, int] = {}
        self.max_disappeared = max_disappeared

    def update(self, detections: List[BoundingBox]) -> Dict[int, BoundingBox]:
        """Update tracker with new detections."""
        if len(detections) == 0:
            for obj_id in list(self.disappeared.keys()):
                self.disappeared[obj_id] += 1
                if self.disappeared[obj_id] > self.max_disappeared:
                    del self.objects[obj_id]
                    del self.disappeared[obj_id]
            return {}

        centroids = np.array([d.center for d in detections])

        if len(self.objects) == 0:
            for centroid, det in zip(centroids, detections):
                self._register(centroid, det)
        else:
            obj_ids = list(self.objects.keys())
            obj_centroids = np.array(list(self.objects.values()))

            # Compute distances
            D = np.linalg.norm(obj_centroids[:, np.newaxis] - centroids, axis=2)

            rows = D.min(axis=1).argsort()
            cols = D.argmin(axis=1)[rows]

            used_rows = set()
            used_cols = set()

            for row, col in zip(rows, cols):
                if row in used_rows or col in used_cols:
                    continue
                if D[row, col] > 100:  # Max distance threshold
                    continue

                obj_id = obj_ids[row]
                self.objects[obj_id] = centroids[col]
                self.disappeared[obj_id] = 0
                used_rows.add(row)
                used_cols.add(col)

            unused_rows = set(range(len(obj_ids))) - used_rows
            unused_cols = set(range(len(detections))) - used_cols

            for row in unused_rows:
                obj_id = obj_ids[row]
                self.disappeared[obj_id] += 1
                if self.disappeared[obj_id] > self.max_disappeared:
                    del self.objects[obj_id]
                    del self.disappeared[obj_id]

            for col in unused_cols:
                self._register(centroids[col], detections[col])

        result = {}
        for obj_id, centroid in self.objects.items():
            for det in detections:
                if np.allclose(det.center, centroid, atol=5):
                    result[obj_id] = det
                    break

        return result

    def _register(self, centroid, detection):
        self.objects[self.next_id] = centroid
        self.disappeared[self.next_id] = 0
        self.next_id += 1


class EventDetector:
    """Rule-based event detection from frame analysis."""

    def __init__(self, fps: float = 30):
        self.fps = fps
        self.frame_buffer: deque = deque(maxlen=int(fps * 5))  # 5 second buffer
        self.ball_history: deque = deque(maxlen=int(fps * 2))  # 2 second ball history
        self.events: List[GameEvent] = []

        # Field zones (normalized coordinates)
        self.goal_zones = {
            "left": (0, 0.4, 0.1, 0.6),  # x1, y1, x2, y2
            "right": (0.9, 0.4, 1.0, 0.6),
        }
        self.penalty_zones = {
            "left": (0, 0.2, 0.17, 0.8),
            "right": (0.83, 0.2, 1.0, 0.8),
        }

    def process_frame(self, analysis: FrameAnalysis) -> List[GameEvent]:
        """Process frame and detect events."""
        self.frame_buffer.append(analysis)

        if analysis.ball:
            self.ball_history.append(analysis.ball)

        new_events = []

        # Check for various events
        if shot_event := self._detect_shot(analysis):
            new_events.append(shot_event)

        if save_event := self._detect_save(analysis):
            new_events.append(save_event)

        if pass_event := self._detect_pass(analysis):
            new_events.append(pass_event)

        if dribble_event := self._detect_dribble(analysis):
            new_events.append(dribble_event)

        if goal_event := self._detect_goal(analysis):
            new_events.append(goal_event)

        self.events.extend(new_events)
        return new_events

    def _detect_shot(self, analysis: FrameAnalysis) -> Optional[GameEvent]:
        """Detect shot on goal."""
        if not analysis.ball or len(self.ball_history) < 5:
            return None

        ball = analysis.ball
        if not ball.velocity:
            return None

        vx, vy = ball.velocity
        speed = np.sqrt(vx**2 + vy**2)

        # Fast ball moving toward goal
        if speed > 50 and abs(vx) > abs(vy) * 2:
            bx, by = ball.bbox.center
            # Normalize coordinates
            frame_width = 5760  # Panorama width
            frame_height = 1080
            nx, ny = bx / frame_width, by / frame_height

            # Check if heading toward goal zone
            for side, (x1, y1, x2, y2) in self.goal_zones.items():
                if (side == "right" and vx > 0) or (side == "left" and vx < 0):
                    return GameEvent(
                        event_type=EventType.SHOT,
                        timestamp_ms=analysis.timestamp_ms,
                        frame_number=analysis.frame_number,
                        confidence=min(0.9, speed / 100),
                        location=(nx, ny),
                        metadata={"direction": side, "speed": speed},
                    )
        return None

    def _detect_save(self, analysis: FrameAnalysis) -> Optional[GameEvent]:
        """Detect goalkeeper save."""
        # Find goalkeeper
        gk = None
        for player in analysis.players:
            if player.is_goalkeeper:
                gk = player
                break

        if not gk or not analysis.ball:
            return None

        # Check if ball near goalkeeper and changes direction
        ball_center = analysis.ball.bbox.center
        gk_center = gk.bbox.center

        dist = np.sqrt((ball_center[0] - gk_center[0])**2 +
                       (ball_center[1] - gk_center[1])**2)

        if dist < 200 and len(self.ball_history) >= 3:
            # Check for direction change
            recent_balls = list(self.ball_history)[-3:]
            if all(b.velocity for b in recent_balls):
                vx_before = recent_balls[0].velocity[0]
                vx_after = recent_balls[-1].velocity[0]

                if vx_before * vx_after < 0:  # Direction changed
                    return GameEvent(
                        event_type=EventType.SAVE,
                        timestamp_ms=analysis.timestamp_ms,
                        frame_number=analysis.frame_number,
                        confidence=0.8,
                        players_involved=[gk.track_id] if gk.track_id else [],
                        location=gk.bbox.center,
                    )
        return None

    def _detect_pass(self, analysis: FrameAnalysis) -> Optional[GameEvent]:
        """Detect pass between players."""
        if not analysis.ball or len(self.ball_history) < 10:
            return None

        # Check if ball transferred between players
        recent_balls = list(self.ball_history)[-10:]

        # Find closest player to ball at start and end
        start_ball = recent_balls[0]
        end_ball = recent_balls[-1]

        def closest_player(ball, players):
            if not players:
                return None, float('inf')

            ball_center = ball.bbox.center
            closest = None
            min_dist = float('inf')

            for p in players:
                dist = np.sqrt((ball_center[0] - p.bbox.center[0])**2 +
                              (ball_center[1] - p.bbox.center[1])**2)
                if dist < min_dist:
                    min_dist = dist
                    closest = p
            return closest, min_dist

        # Use buffered frames
        if len(self.frame_buffer) < 10:
            return None

        start_frame = list(self.frame_buffer)[-10]
        end_frame = analysis

        start_player, start_dist = closest_player(start_ball, start_frame.players)
        end_player, end_dist = closest_player(end_ball, end_frame.players)

        if (start_player and end_player and
            start_dist < 100 and end_dist < 100 and
            start_player.track_id != end_player.track_id):
            return GameEvent(
                event_type=EventType.PASS,
                timestamp_ms=analysis.timestamp_ms,
                frame_number=analysis.frame_number,
                confidence=0.7,
                players_involved=[p.track_id for p in [start_player, end_player]
                                 if p.track_id],
            )
        return None

    def _detect_dribble(self, analysis: FrameAnalysis) -> Optional[GameEvent]:
        """Detect player dribbling."""
        if not analysis.ball or len(self.frame_buffer) < 30:
            return None

        # Check if same player has ball for extended period with movement
        ball_center = analysis.ball.bbox.center

        closest_player = None
        min_dist = float('inf')

        for player in analysis.players:
            dist = np.sqrt((ball_center[0] - player.bbox.center[0])**2 +
                          (ball_center[1] - player.bbox.center[1])**2)
            if dist < min_dist:
                min_dist = dist
                closest_player = player

        if closest_player and min_dist < 100:
            # Check player has maintained ball possession
            possession_count = 0
            for frame in list(self.frame_buffer)[-30:]:
                if frame.ball:
                    for p in frame.players:
                        if p.track_id == closest_player.track_id:
                            dist = np.sqrt(
                                (frame.ball.bbox.center[0] - p.bbox.center[0])**2 +
                                (frame.ball.bbox.center[1] - p.bbox.center[1])**2
                            )
                            if dist < 100:
                                possession_count += 1

            if possession_count > 20:  # ~0.6 seconds of possession
                return GameEvent(
                    event_type=EventType.DRIBBLE,
                    timestamp_ms=analysis.timestamp_ms,
                    frame_number=analysis.frame_number,
                    confidence=possession_count / 30,
                    players_involved=[closest_player.track_id] if closest_player.track_id else [],
                )
        return None

    def _detect_goal(self, analysis: FrameAnalysis) -> Optional[GameEvent]:
        """Detect goal scored."""
        if not analysis.ball:
            return None

        ball_center = analysis.ball.bbox.center

        # Normalize
        frame_width = 5760
        frame_height = 1080
        nx, ny = ball_center[0] / frame_width, ball_center[1] / frame_height

        # Check if ball in goal zone and ball "disappeared" or stopped
        for side, (x1, y1, x2, y2) in self.goal_zones.items():
            if x1 <= nx <= x2 and y1 <= ny <= y2:
                # Check recent ball history for high-speed entry
                if len(self.ball_history) >= 5:
                    recent = list(self.ball_history)[-5:]
                    speeds = []
                    for b in recent:
                        if b.velocity:
                            speeds.append(np.sqrt(b.velocity[0]**2 + b.velocity[1]**2))

                    if speeds and max(speeds) > 60:
                        return GameEvent(
                            event_type=EventType.GOAL,
                            timestamp_ms=analysis.timestamp_ms,
                            frame_number=analysis.frame_number,
                            confidence=0.9,
                            metadata={"goal_side": side},
                        )
        return None

    def get_highlights(self, min_confidence: float = 0.7) -> List[GameEvent]:
        """Get high-confidence events as highlights."""
        highlights = []
        for event in self.events:
            if event.confidence >= min_confidence:
                if event.event_type in [EventType.GOAL, EventType.SHOT,
                                         EventType.SAVE, EventType.DRIBBLE]:
                    highlights.append(event)
        return highlights


class MLPipeline:
    """Main ML pipeline for video analysis."""

    def __init__(self, config: 'MLConfig'):
        self.config = config
        self.device = config.device

        # Models (lazy loaded)
        self._player_model = None
        self._ball_model = None
        self._pose_model = None

        # Trackers
        self.player_tracker = ObjectTracker(max_disappeared=30)
        self.ball_tracker = ObjectTracker(max_disappeared=15)

        # Event detector
        self.event_detector = EventDetector()

        # Processing state
        self._processing = False
        self._lock = threading.Lock()

        logger.info(f"MLPipeline initialized with device: {self.device}")

    @property
    def player_model(self):
        """Lazy load player detection model."""
        if self._player_model is None:
            try:
                from ultralytics import YOLO
                self._player_model = YOLO(self.config.player_model)
                if "cuda" in self.device:
                    self._player_model.to(self.device)
                logger.info(f"Loaded player model: {self.config.player_model}")
            except Exception as e:
                logger.error(f"Failed to load player model: {e}")
                raise
        return self._player_model

    @property
    def ball_model(self):
        """Lazy load ball detection model."""
        if self._ball_model is None:
            try:
                from ultralytics import YOLO
                self._ball_model = YOLO(self.config.ball_model)
                if "cuda" in self.device:
                    self._ball_model.to(self.device)
                logger.info(f"Loaded ball model: {self.config.ball_model}")
            except Exception as e:
                logger.error(f"Failed to load ball model: {e}")
                raise
        return self._ball_model

    @property
    def pose_model(self):
        """Lazy load pose estimation model."""
        if self._pose_model is None:
            try:
                from ultralytics import YOLO
                self._pose_model = YOLO(self.config.pose_model)
                if "cuda" in self.device:
                    self._pose_model.to(self.device)
                logger.info(f"Loaded pose model: {self.config.pose_model}")
            except Exception as e:
                logger.error(f"Failed to load pose model: {e}")
                raise
        return self._pose_model

    def analyze_frame(self, frame: np.ndarray, frame_number: int,
                      fps: float = 30) -> FrameAnalysis:
        """Analyze a single frame."""
        timestamp_ms = (frame_number / fps) * 1000

        analysis = FrameAnalysis(
            frame_number=frame_number,
            timestamp_ms=timestamp_ms,
        )

        # Detect players (COCO class 0 = person)
        player_results = self.player_model.predict(
            frame,
            conf=self.config.confidence_threshold,
            classes=[0],  # Person only
            verbose=False
        )

        player_boxes = []
        for result in player_results:
            for box in result.boxes:
                bbox = BoundingBox(
                    x1=float(box.xyxy[0][0]),
                    y1=float(box.xyxy[0][1]),
                    x2=float(box.xyxy[0][2]),
                    y2=float(box.xyxy[0][3]),
                    confidence=float(box.conf[0]),
                    class_id=int(box.cls[0]),
                    class_name="person",
                )
                player_boxes.append(bbox)

        # Track players
        tracked_players = self.player_tracker.update(player_boxes)

        for track_id, bbox in tracked_players.items():
            # Detect goalkeeper based on position (near goal zones)
            is_gk = self._is_goalkeeper_position(bbox, frame.shape)

            player = PlayerDetection(
                bbox=bbox,
                track_id=track_id,
                is_goalkeeper=is_gk,
            )
            analysis.players.append(player)

        # Detect ball (COCO class 32 = sports ball)
        ball_results = self.ball_model.predict(
            frame,
            conf=0.3,  # Lower threshold for ball
            classes=[32],  # Sports ball
            verbose=False
        )

        ball_boxes = []
        for result in ball_results:
            for box in result.boxes:
                bbox = BoundingBox(
                    x1=float(box.xyxy[0][0]),
                    y1=float(box.xyxy[0][1]),
                    x2=float(box.xyxy[0][2]),
                    y2=float(box.xyxy[0][3]),
                    confidence=float(box.conf[0]),
                    class_id=int(box.cls[0]),
                    class_name="ball",
                )
                ball_boxes.append(bbox)

        # Track ball
        if ball_boxes:
            tracked_balls = self.ball_tracker.update(ball_boxes)
            if tracked_balls:
                # Take highest confidence ball
                best_ball = max(tracked_balls.items(),
                               key=lambda x: x[1].confidence)
                track_id, bbox = best_ball

                # Calculate velocity from history
                velocity = self._calculate_velocity(bbox, self.event_detector.ball_history)

                analysis.ball = BallDetection(
                    bbox=bbox,
                    track_id=track_id,
                    velocity=velocity,
                )

        return analysis

    def _is_goalkeeper_position(self, bbox: BoundingBox, frame_shape: tuple) -> bool:
        """Check if player is in goalkeeper position."""
        cx, cy = bbox.center
        frame_width = frame_shape[1]

        # Normalize x position
        nx = cx / frame_width

        # Near either goal
        return nx < 0.12 or nx > 0.88

    def _calculate_velocity(self, current_bbox: BoundingBox,
                           history: deque) -> Optional[Tuple[float, float]]:
        """Calculate ball velocity from history."""
        if len(history) < 2:
            return None

        prev = history[-1]
        dx = current_bbox.center[0] - prev.bbox.center[0]
        dy = current_bbox.center[1] - prev.bbox.center[1]

        return (dx, dy)

    def process_video(self, video_path: str,
                      output_json: Optional[str] = None,
                      callback: Optional[callable] = None) -> Dict:
        """Process entire video and extract events."""
        logger.info(f"Processing video: {video_path}")

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Could not open video: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration_ms = (total_frames / fps) * 1000

        self.event_detector = EventDetector(fps=fps)

        # Process every N frames based on detection_fps
        frame_skip = max(1, int(fps / self.config.detection_fps))

        frame_number = 0
        processed_frames = 0
        all_events = []

        self._processing = True

        try:
            while self._processing:
                ret, frame = cap.read()
                if not ret:
                    break

                if frame_number % frame_skip == 0:
                    # Analyze frame
                    analysis = self.analyze_frame(frame, frame_number, fps)

                    # Detect events
                    events = self.event_detector.process_frame(analysis)
                    all_events.extend(events)

                    processed_frames += 1

                    if callback:
                        callback({
                            "frame_number": frame_number,
                            "total_frames": total_frames,
                            "progress": frame_number / total_frames,
                            "events_found": len(all_events),
                        })

                frame_number += 1
        finally:
            cap.release()
            self._processing = False

        # Generate results
        results = {
            "video_path": video_path,
            "duration_ms": duration_ms,
            "total_frames": total_frames,
            "fps": fps,
            "frames_analyzed": processed_frames,
            "events": [e.to_dict() for e in all_events],
            "highlights": [e.to_dict() for e in self.event_detector.get_highlights()],
            "summary": self._generate_summary(all_events),
        }

        if output_json:
            with open(output_json, 'w') as f:
                json.dump(results, f, indent=2)
            logger.info(f"Results saved to: {output_json}")

        return results

    def _generate_summary(self, events: List[GameEvent]) -> Dict:
        """Generate event summary statistics."""
        summary = {
            "total_events": len(events),
            "by_type": {},
        }

        for event in events:
            event_type = event.event_type.value
            if event_type not in summary["by_type"]:
                summary["by_type"][event_type] = 0
            summary["by_type"][event_type] += 1

        return summary

    def stop(self):
        """Stop processing."""
        self._processing = False


class BatchProcessor:
    """Process multiple videos in batch."""

    def __init__(self, config: 'MLConfig', num_workers: int = 2):
        self.config = config
        self.num_workers = num_workers
        self.job_queue = queue.Queue()
        self.results = {}
        self._workers = []
        self._running = False

    def start(self):
        """Start worker threads."""
        self._running = True
        for i in range(self.num_workers):
            worker = threading.Thread(target=self._worker_loop, args=(i,))
            worker.daemon = True
            worker.start()
            self._workers.append(worker)
        logger.info(f"Started {self.num_workers} ML workers")

    def stop(self):
        """Stop all workers."""
        self._running = False
        for _ in self._workers:
            self.job_queue.put(None)
        for worker in self._workers:
            worker.join(timeout=5)
        self._workers = []

    def _worker_loop(self, worker_id: int):
        """Worker thread main loop."""
        pipeline = MLPipeline(self.config)
        logger.info(f"ML Worker {worker_id} started")

        while self._running:
            try:
                job = self.job_queue.get(timeout=1)
                if job is None:
                    break

                job_id, video_path, output_path = job
                logger.info(f"Worker {worker_id} processing: {video_path}")

                try:
                    results = pipeline.process_video(video_path, output_path)
                    self.results[job_id] = {
                        "status": "completed",
                        "results": results,
                    }
                except Exception as e:
                    logger.error(f"Worker {worker_id} error: {e}")
                    self.results[job_id] = {
                        "status": "failed",
                        "error": str(e),
                    }
            except queue.Empty:
                continue

    def submit(self, job_id: str, video_path: str, output_path: str):
        """Submit video for processing."""
        self.job_queue.put((job_id, video_path, output_path))
        self.results[job_id] = {"status": "queued"}

    def get_status(self, job_id: str) -> Dict:
        """Get job status."""
        return self.results.get(job_id, {"status": "unknown"})
