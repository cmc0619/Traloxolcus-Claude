"""
Offload client for uploading recordings to the central server.

Handles:
- Uploading recordings with checksum verification
- Retry logic for network failures
- Confirming successful uploads
- Marking recordings as offloaded
"""

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from enum import Enum

import requests

logger = logging.getLogger(__name__)


class OffloadStatus(Enum):
    PENDING = "pending"
    UPLOADING = "uploading"
    CONFIRMING = "confirming"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class OffloadJob:
    """Represents a recording offload job."""
    recording_id: str
    session_id: str
    camera_id: str
    file_path: Path
    manifest_path: Path
    status: OffloadStatus = OffloadStatus.PENDING
    attempts: int = 0
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recording_id": self.recording_id,
            "session_id": self.session_id,
            "camera_id": self.camera_id,
            "file_path": str(self.file_path),
            "status": self.status.value,
            "attempts": self.attempts,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class OffloadClient:
    """
    Client for uploading recordings to the central server.

    Features:
    - Automatic upload of completed recordings
    - Checksum verification
    - Retry with exponential backoff
    - Progress tracking
    - Confirmation and local cleanup
    """

    MAX_RETRIES = 5
    INITIAL_RETRY_DELAY = 5  # seconds
    CHUNK_SIZE = 8 * 1024 * 1024  # 8MB chunks

    def __init__(self, config, storage_manager=None):
        """
        Initialize offload client.

        Args:
            config: Configuration with server URL
            storage_manager: StorageManager for marking offloaded files
        """
        self.config = config
        self.storage = storage_manager

        # Server URL from config.offload dataclass
        offload_config = getattr(config, 'offload', None)
        if offload_config:
            self.server_url = getattr(offload_config, 'server_url', '') or 'http://localhost:8081'
            self.auto_upload = getattr(offload_config, 'auto_upload', False)
            self.delete_after_confirm = getattr(offload_config, 'verify_checksum', True)
            self.max_retries = getattr(offload_config, 'retry_count', 5)
            self.retry_delay = getattr(offload_config, 'retry_delay_sec', 5)
        else:
            self.server_url = 'http://localhost:8081'
            self.auto_upload = False
            self.delete_after_confirm = False
            self.max_retries = 5
            self.retry_delay = 5

        self.api_base = f"{self.server_url}/api/v1"

        # Job queue
        self._jobs: Dict[str, OffloadJob] = {}
        self._queue: List[str] = []
        self._lock = threading.Lock()

        # Background worker
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None

        # Session for connection reuse
        self._session = requests.Session()
        self._session.timeout = 30

    def start(self) -> None:
        """Start the background offload worker."""
        if self.auto_upload:
            self._running = True
            self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker_thread.start()
            logger.info(f"Offload client started, server: {self.server_url}")

    def stop(self) -> None:
        """Stop the offload worker."""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
        self._session.close()

    def queue_upload(
        self,
        recording_id: str,
        session_id: str,
        camera_id: str,
        file_path: Path,
        manifest_path: Path
    ) -> str:
        """
        Queue a recording for upload.

        Returns:
            Job ID
        """
        job = OffloadJob(
            recording_id=recording_id,
            session_id=session_id,
            camera_id=camera_id,
            file_path=file_path,
            manifest_path=manifest_path,
        )

        with self._lock:
            self._jobs[recording_id] = job
            self._queue.append(recording_id)

        logger.info(f"Queued {recording_id} for offload")
        return recording_id

    def upload_now(
        self,
        session_id: str,
        camera_id: str,
        file_path: Path,
        manifest_path: Path
    ) -> Dict[str, Any]:
        """
        Upload a recording immediately (blocking).

        Returns:
            Result dict with success status
        """
        recording_id = f"{session_id}_{camera_id}"

        job = OffloadJob(
            recording_id=recording_id,
            session_id=session_id,
            camera_id=camera_id,
            file_path=file_path,
            manifest_path=manifest_path,
        )

        return self._process_job(job)

    def get_job_status(self, recording_id: str) -> Optional[Dict[str, Any]]:
        """Get status of an offload job."""
        job = self._jobs.get(recording_id)
        if job:
            return job.to_dict()
        return None

    def get_all_jobs(self) -> List[Dict[str, Any]]:
        """Get all job statuses."""
        return [job.to_dict() for job in self._jobs.values()]

    def get_pending_count(self) -> int:
        """Get count of pending jobs."""
        return len(self._queue)

    def _worker_loop(self) -> None:
        """Background worker that processes upload queue."""
        while self._running:
            job_id = None

            with self._lock:
                if self._queue:
                    job_id = self._queue.pop(0)

            if job_id:
                job = self._jobs.get(job_id)
                if job:
                    self._process_job(job)
            else:
                time.sleep(5)  # Wait for new jobs

    def _process_job(self, job: OffloadJob) -> Dict[str, Any]:
        """Process a single offload job."""
        job.status = OffloadStatus.UPLOADING
        job.started_at = datetime.now()

        # Retry loop
        while job.attempts < self.max_retries:
            job.attempts += 1

            try:
                # Check file exists
                if not job.file_path.exists():
                    raise FileNotFoundError(f"Recording file not found: {job.file_path}")

                # Load manifest
                manifest = {}
                if job.manifest_path.exists():
                    with open(job.manifest_path) as f:
                        manifest = json.load(f)

                # Get checksum from manifest or calculate
                checksum = manifest.get("checksum", {}).get("value")
                if not checksum:
                    checksum = self._calculate_checksum(job.file_path)

                # Upload file
                logger.info(f"Uploading {job.recording_id} (attempt {job.attempts})")
                result = self._upload_file(job, manifest, checksum)

                if not result.get("success"):
                    raise Exception(result.get("error", "Upload failed"))

                # Confirm upload
                job.status = OffloadStatus.CONFIRMING
                confirm_result = self._confirm_upload(job.session_id, job.camera_id)

                if not confirm_result.get("success"):
                    raise Exception("Upload confirmation failed")

                # Verify checksum matches
                if confirm_result.get("checksum_sha256") != checksum:
                    raise Exception("Checksum mismatch after upload")

                # Success!
                job.status = OffloadStatus.COMPLETED
                job.completed_at = datetime.now()

                # Mark as offloaded in storage manager
                if self.storage:
                    self.storage.mark_offloaded(job.recording_id)

                logger.info(f"Successfully offloaded {job.recording_id}")

                return {
                    "success": True,
                    "recording_id": job.recording_id,
                    "session_id": job.session_id,
                    "camera_id": job.camera_id,
                }

            except Exception as e:
                logger.warning(f"Offload attempt {job.attempts} failed: {e}")
                job.error = str(e)

                if job.attempts < self.max_retries:
                    # Exponential backoff
                    delay = self.retry_delay * (2 ** (job.attempts - 1))
                    logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)

        # All retries exhausted
        job.status = OffloadStatus.FAILED
        job.completed_at = datetime.now()
        logger.error(f"Offload failed after {job.attempts} attempts: {job.recording_id}")

        return {
            "success": False,
            "recording_id": job.recording_id,
            "error": job.error,
        }

    def _upload_file(
        self,
        job: OffloadJob,
        manifest: Dict[str, Any],
        checksum: str
    ) -> Dict[str, Any]:
        """Upload file to server."""
        url = f"{self.api_base}/upload"

        with open(job.file_path, "rb") as f:
            files = {
                "file": (job.file_path.name, f, "video/mp4"),
            }
            data = {
                "session_id": job.session_id,
                "camera_id": job.camera_id,
                "checksum": checksum,
                "manifest": json.dumps(manifest),
            }

            response = self._session.post(
                url,
                files=files,
                data=data,
                timeout=3600,  # 1 hour timeout for large files
            )

        if response.status_code in (200, 201):
            return response.json()
        else:
            return {
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text}"
            }

    def _confirm_upload(self, session_id: str, camera_id: str) -> Dict[str, Any]:
        """Confirm upload with server."""
        url = f"{self.api_base}/upload/confirm"

        response = self._session.post(
            url,
            json={"session_id": session_id, "camera_id": camera_id},
            timeout=30,
        )

        if response.status_code == 200:
            return response.json()
        return {"success": False, "error": f"HTTP {response.status_code}"}

    def _calculate_checksum(self, file_path: Path) -> str:
        """Calculate SHA-256 checksum of file."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(self.CHUNK_SIZE)
                if not chunk:
                    break
                sha256.update(chunk)
        return sha256.hexdigest()

    def check_server_health(self) -> Dict[str, Any]:
        """Check if server is reachable."""
        try:
            response = self._session.get(
                f"{self.api_base}/health",
                timeout=5
            )
            if response.status_code == 200:
                return {"healthy": True, **response.json()}
            return {"healthy": False, "status_code": response.status_code}
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    def get_status(self) -> Dict[str, Any]:
        """Get offload client status."""
        server_health = self.check_server_health()

        return {
            "enabled": self.auto_upload,
            "server_url": self.server_url,
            "server_healthy": server_health.get("healthy", False),
            "pending_uploads": self.get_pending_count(),
            "total_jobs": len(self._jobs),
            "completed_jobs": sum(
                1 for j in self._jobs.values()
                if j.status == OffloadStatus.COMPLETED
            ),
            "failed_jobs": sum(
                1 for j in self._jobs.values()
                if j.status == OffloadStatus.FAILED
            ),
        }
