"""
Video stitching module for Soccer Rig Server.

Combines CAM_L, CAM_C, CAM_R into a panoramic view.
"""

import json
import logging
import subprocess
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class JobStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class StitchJob:
    id: str
    session_id: str
    status: JobStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: float = 0.0
    error: Optional[str] = None
    output_path: Optional[Path] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "progress": self.progress,
            "error": self.error,
            "output_path": str(self.output_path) if self.output_path else None,
        }


class VideoStitcher:
    """
    Stitches multiple camera views into a panorama.

    Uses FFmpeg to horizontally stack the three camera feeds:
    [CAM_L][CAM_C][CAM_R] -> Panorama

    For more advanced stitching (with blending), consider using
    OpenCV or specialized panorama tools.
    """

    def __init__(self, config, storage):
        self.config = config
        self.storage = storage
        self._jobs: Dict[str, StitchJob] = {}
        self._lock = threading.Lock()

        # Worker thread
        self._queue = []
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        """Start the stitcher worker thread."""
        self._running = True
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        logger.info("Stitcher worker started")

    def stop(self) -> None:
        """Stop the stitcher worker."""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5)

    def queue_stitch(self, session_id: str) -> str:
        """
        Queue a stitching job.

        Returns:
            Job ID
        """
        job_id = str(uuid.uuid4())[:8]

        job = StitchJob(
            id=job_id,
            session_id=session_id,
            status=JobStatus.QUEUED,
            created_at=datetime.now(),
        )

        with self._lock:
            self._jobs[job_id] = job
            self._queue.append(job_id)

        logger.info(f"Queued stitch job {job_id} for session {session_id}")
        return job_id

    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a job."""
        job = self._jobs.get(job_id)
        if job:
            return job.to_dict()
        return None

    def _worker_loop(self) -> None:
        """Background worker that processes stitch jobs."""
        import time

        while self._running:
            job_id = None

            with self._lock:
                if self._queue:
                    job_id = self._queue.pop(0)

            if job_id:
                self._process_job(job_id)
            else:
                time.sleep(1)

    def _process_job(self, job_id: str) -> None:
        """Process a single stitch job."""
        job = self._jobs.get(job_id)
        if not job:
            return

        job.status = JobStatus.RUNNING
        job.started_at = datetime.now()

        try:
            session = self.storage.get_session(job.session_id)
            if not session:
                raise ValueError(f"Session {job.session_id} not found")

            if len(session.recordings) < 3:
                raise ValueError("Session incomplete - need all 3 cameras")

            # Get input paths
            cam_l = session.recordings.get("CAM_L")
            cam_c = session.recordings.get("CAM_C")
            cam_r = session.recordings.get("CAM_R")

            if not all([cam_l, cam_c, cam_r]):
                raise ValueError("Missing camera recordings")

            # Output path
            session_dir = Path(self.config.storage.base_path) / "sessions" / job.session_id
            output_path = session_dir / "stitched.mp4"

            # Run FFmpeg
            self._run_ffmpeg_stitch(
                inputs=[cam_l.path, cam_c.path, cam_r.path],
                output=output_path,
                job=job,
            )

            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now()
            job.output_path = output_path
            job.progress = 100.0

            # Update session
            session.stitched = True
            session.stitched_path = output_path

            logger.info(f"Stitch job {job_id} completed: {output_path}")

        except Exception as e:
            logger.error(f"Stitch job {job_id} failed: {e}")
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.completed_at = datetime.now()

    def _run_ffmpeg_stitch(
        self,
        inputs: list,
        output: Path,
        job: StitchJob
    ) -> None:
        """
        Run FFmpeg to stitch videos horizontally.

        Simple horizontal stack: [L][C][R]
        """
        cfg = self.config.processing

        # Build filter for horizontal stack
        # Scale each to 1/3 of output width, then hstack
        input_width = cfg.stitch_output_width // 3
        input_height = cfg.stitch_output_height

        filter_complex = (
            f"[0:v]scale={input_width}:{input_height}[l];"
            f"[1:v]scale={input_width}:{input_height}[c];"
            f"[2:v]scale={input_width}:{input_height}[r];"
            f"[l][c][r]hstack=inputs=3[v]"
        )

        cmd = [
            cfg.ffmpeg_path,
            "-y",  # Overwrite output
            "-i", str(inputs[0]),  # CAM_L
            "-i", str(inputs[1]),  # CAM_C
            "-i", str(inputs[2]),  # CAM_R
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "1:a?",  # Audio from center camera
            "-c:v", cfg.stitch_codec,
            "-crf", str(cfg.stitch_crf),
            "-preset", "medium",
            "-c:a", "aac",
            "-b:a", "128k",
            str(output),
        ]

        logger.info(f"Running FFmpeg stitch: {' '.join(cmd)}")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Monitor progress (simplified - could parse FFmpeg output for real progress)
        stdout, stderr = process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"FFmpeg failed: {error_msg}")

        if not output.exists():
            raise RuntimeError("Output file not created")


class CeleryStitcher:
    """
    Celery-based stitcher for distributed processing.

    Use this in production for async job processing.
    """

    def __init__(self, config, storage):
        self.config = config
        self.storage = storage

        # This would integrate with Celery
        # from .tasks import stitch_task
        # self.celery_app = ...

    def queue_stitch(self, session_id: str) -> str:
        """Queue a stitch job via Celery."""
        # task = stitch_task.delay(session_id)
        # return task.id
        raise NotImplementedError("Celery stitcher not implemented yet")

    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get Celery task status."""
        # result = AsyncResult(job_id)
        # return {"status": result.status, ...}
        raise NotImplementedError("Celery stitcher not implemented yet")
