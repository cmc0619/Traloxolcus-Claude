"""
Main Processing Server Application.

Orchestrates:
- Ingest: Receives uploads from Pi camera nodes
- Stitcher: Combines 3 camera feeds into panorama
- ML Pipeline: Detects events and generates metadata
- Push Service: Syncs to viewer server
"""

import os
import sys
import json
import logging
import argparse
import threading
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

from .config import Config
from .ingest import IngestServer, RecordingSession
from .stitcher import VideoStitcher
from .ml import MLPipeline, EventType
from .push import PushService, PushJob, SyncManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ProcessingPipeline:
    """Main processing pipeline coordinator."""

    def __init__(self, config: Config):
        self.config = config

        # Initialize components
        self.ingest = IngestServer(config.server, config.storage)
        self.stitcher = VideoStitcher(config)
        self.ml_pipeline = MLPipeline(config.ml) if config.ml.enabled else None
        self.push_service = PushService(config.push) if config.push.enabled else None

        if self.push_service:
            self.sync_manager = SyncManager(
                self.push_service,
                state_file=str(Path(config.storage.output_path) / "sync_state.json")
            )

        # Set up callbacks
        self.ingest.on_session_ready = self._on_session_ready

        # Processing queue
        self._processing_queue = []
        self._processing_lock = threading.Lock()
        self._processing_thread = None
        self._running = False

        logger.info("ProcessingPipeline initialized")

    def _on_session_ready(self, session_id: str, session: RecordingSession):
        """Called when a recording session is ready for processing."""
        logger.info(f"Session ready for processing: {session_id}")

        with self._processing_lock:
            self._processing_queue.append(session_id)

    def _processing_loop(self):
        """Background processing loop."""
        while self._running:
            session_id = None

            with self._processing_lock:
                if self._processing_queue:
                    session_id = self._processing_queue.pop(0)

            if session_id:
                try:
                    self._process_session(session_id)
                except Exception as e:
                    logger.error(f"Error processing session {session_id}: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                time.sleep(1)

    def _process_session(self, session_id: str):
        """Process a single session through the pipeline."""
        logger.info(f"Processing session: {session_id}")

        session = self.ingest.get_session(session_id)
        if not session:
            logger.error(f"Session not found: {session_id}")
            return

        self.ingest.mark_processing(session_id)

        output_dir = Path(self.config.storage.output_path) / session_id
        output_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Stitch videos
        logger.info(f"Step 1: Stitching videos for session {session_id}")

        # Sort recordings by node ID to ensure consistent ordering
        sorted_recordings = sorted(session.recordings.items(), key=lambda x: x[0])
        input_videos = [path for node_id, path in sorted_recordings]

        stitched_path = str(output_dir / f"{session_id}_panorama.mp4")

        stitch_job_id = self.stitcher.queue_stitch(
            session_id=session_id,
            input_videos=input_videos,
            output_path=stitched_path
        )

        # Wait for stitching to complete
        while True:
            status = self.stitcher.get_status(stitch_job_id)
            if status["status"] == "completed":
                logger.info(f"Stitching completed for {session_id}")
                break
            elif status["status"] == "failed":
                logger.error(f"Stitching failed: {status.get('error')}")
                return
            time.sleep(2)

        # Step 2: ML Analysis
        metadata = {
            "session_id": session_id,
            "created_at": datetime.now().isoformat(),
            "source_recordings": sorted_recordings,
            "events": [],
            "highlights": [],
        }

        if self.ml_pipeline and self.config.ml.enabled:
            logger.info(f"Step 2: Running ML analysis for session {session_id}")

            events_path = str(output_dir / f"{session_id}_events.json")

            def progress_callback(progress):
                if progress["frame_number"] % 300 == 0:  # Log every 10 seconds at 30fps
                    logger.info(
                        f"ML Progress: {progress['progress']*100:.1f}% "
                        f"({progress['events_found']} events)"
                    )

            try:
                ml_results = self.ml_pipeline.process_video(
                    stitched_path,
                    output_json=events_path,
                    callback=progress_callback
                )

                metadata["events"] = ml_results.get("events", [])
                metadata["highlights"] = ml_results.get("highlights", [])
                metadata["ml_summary"] = ml_results.get("summary", {})

                logger.info(
                    f"ML analysis complete: {len(metadata['events'])} events, "
                    f"{len(metadata['highlights'])} highlights"
                )
            except Exception as e:
                logger.error(f"ML analysis failed: {e}")
                # Continue without ML results
        else:
            logger.info("Step 2: ML analysis disabled, skipping")

        # Add manifest data if available
        if session.manifest:
            metadata["manifest"] = session.manifest

        # Save metadata
        metadata_path = str(output_dir / f"{session_id}_metadata.json")
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Metadata saved to {metadata_path}")

        # Generate thumbnail
        thumbnail_path = str(output_dir / f"{session_id}_thumb.jpg")
        self._generate_thumbnail(stitched_path, thumbnail_path)

        # Step 3: Push to viewer server
        if self.push_service and self.config.push.enabled:
            logger.info(f"Step 3: Pushing to viewer server for session {session_id}")

            push_job = PushJob(
                job_id=f"push_{session_id}_{int(time.time())}",
                session_id=session_id,
                video_path=stitched_path,
                metadata_path=metadata_path,
                thumbnail_path=thumbnail_path,
            )

            self.push_service.queue_push(push_job)

            # Wait for push to complete
            while True:
                result = self.push_service.get_status(push_job.job_id)
                if result and result.message != "Queued":
                    if result.success:
                        logger.info(f"Push completed: {result.remote_url}")
                        self.sync_manager.mark_synced(session_id)
                    else:
                        logger.error(f"Push failed: {result.message}")
                    break
                time.sleep(2)
        else:
            logger.info("Step 3: Push service disabled, skipping")

        self.ingest.mark_done(session_id)
        logger.info(f"Session {session_id} processing complete!")

    def _generate_thumbnail(self, video_path: str, output_path: str,
                           time_offset: float = 30.0):
        """Generate thumbnail from video."""
        import subprocess

        try:
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(time_offset),
                "-i", video_path,
                "-vframes", "1",
                "-vf", "scale=640:-1",
                output_path
            ]
            subprocess.run(cmd, capture_output=True, check=True)
            logger.info(f"Generated thumbnail: {output_path}")
        except Exception as e:
            logger.error(f"Failed to generate thumbnail: {e}")

    def start(self):
        """Start all services."""
        logger.info("Starting processing pipeline...")

        self._running = True

        # Start stitcher
        self.stitcher.start()

        # Start push service
        if self.push_service:
            self.push_service.start()

        # Start processing thread
        self._processing_thread = threading.Thread(
            target=self._processing_loop,
            daemon=True
        )
        self._processing_thread.start()

        logger.info("Processing pipeline started")

    def stop(self):
        """Stop all services."""
        logger.info("Stopping processing pipeline...")

        self._running = False

        if self._processing_thread:
            self._processing_thread.join(timeout=10)

        self.stitcher.stop()

        if self.push_service:
            self.push_service.stop()

        logger.info("Processing pipeline stopped")

    def run_server(self, host: Optional[str] = None, port: Optional[int] = None):
        """Run the ingest server (blocking)."""
        self.start()

        try:
            self.ingest.run(host=host, port=port)
        finally:
            self.stop()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Soccer Rig Processing Server")
    parser.add_argument(
        "--config", "-c",
        help="Path to configuration file",
        default=None
    )
    parser.add_argument(
        "--host",
        help="Server host",
        default="0.0.0.0"
    )
    parser.add_argument(
        "--port", "-p",
        help="Server port",
        type=int,
        default=5100
    )
    parser.add_argument(
        "--debug",
        help="Enable debug logging",
        action="store_true"
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load configuration
    config = Config.load(args.config)

    logger.info("=" * 60)
    logger.info("Soccer Rig Processing Server")
    logger.info("=" * 60)
    logger.info(f"Incoming path: {config.storage.incoming_path}")
    logger.info(f"Output path: {config.storage.output_path}")
    logger.info(f"GPU stitching: {config.stitcher.use_gpu}")
    logger.info(f"ML enabled: {config.ml.enabled}")
    logger.info(f"Push enabled: {config.push.enabled}")
    if config.push.enabled:
        logger.info(f"Push method: {config.push.method}")
        logger.info(f"Viewer server: {config.push.viewer_server_url}")
    logger.info("=" * 60)

    # Create and run pipeline
    pipeline = ProcessingPipeline(config)
    pipeline.run_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
