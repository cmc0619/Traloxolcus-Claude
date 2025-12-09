"""
Push Service for syncing processed content to viewer server.

Supports multiple transfer methods: API upload, rsync, and S3.
"""

import os
import json
import time
import hashlib
import logging
import threading
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict, List, Any
from queue import Queue, Empty
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


@dataclass
class PushJob:
    """A job to push content to viewer server."""
    job_id: str
    session_id: str
    video_path: str
    metadata_path: str  # JSON with events/timestamps
    thumbnail_path: Optional[str] = None
    priority: int = 5  # 1-10, lower = higher priority


@dataclass
class PushResult:
    """Result of a push operation."""
    job_id: str
    success: bool
    message: str
    remote_url: Optional[str] = None
    transfer_time_seconds: float = 0
    bytes_transferred: int = 0


class ChunkedUploader:
    """Upload large files in chunks with resume support."""

    def __init__(self, api_url: str, api_key: str, chunk_size_mb: int = 100):
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.chunk_size = chunk_size_mb * 1024 * 1024

        # Setup session with retries
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
        })

    def upload_file(self, local_path: str, remote_name: str,
                    session_id: str, callback: Optional[callable] = None) -> Dict:
        """Upload file in chunks."""
        file_path = Path(local_path)
        file_size = file_path.stat().st_size
        file_hash = self._compute_hash(local_path)

        # Initialize upload
        init_response = self.session.post(
            f"{self.api_url}/api/upload/init",
            json={
                "filename": remote_name,
                "session_id": session_id,
                "file_size": file_size,
                "file_hash": file_hash,
                "chunk_size": self.chunk_size,
            }
        )
        init_response.raise_for_status()
        init_data = init_response.json()

        upload_id = init_data["upload_id"]
        start_chunk = init_data.get("resume_chunk", 0)

        logger.info(f"Starting upload {upload_id}, resuming from chunk {start_chunk}")

        # Upload chunks
        bytes_uploaded = start_chunk * self.chunk_size

        with open(local_path, 'rb') as f:
            f.seek(start_chunk * self.chunk_size)
            chunk_index = start_chunk

            while True:
                chunk_data = f.read(self.chunk_size)
                if not chunk_data:
                    break

                chunk_hash = hashlib.md5(chunk_data).hexdigest()

                response = self.session.post(
                    f"{self.api_url}/api/upload/chunk",
                    data={
                        "upload_id": upload_id,
                        "chunk_index": chunk_index,
                        "chunk_hash": chunk_hash,
                    },
                    files={"chunk": chunk_data}
                )
                response.raise_for_status()

                bytes_uploaded += len(chunk_data)
                chunk_index += 1

                if callback:
                    callback({
                        "bytes_uploaded": bytes_uploaded,
                        "total_bytes": file_size,
                        "progress": bytes_uploaded / file_size,
                        "chunk": chunk_index,
                    })

        # Finalize upload
        final_response = self.session.post(
            f"{self.api_url}/api/upload/finalize",
            json={
                "upload_id": upload_id,
                "total_chunks": chunk_index,
                "file_hash": file_hash,
            }
        )
        final_response.raise_for_status()

        return final_response.json()

    def _compute_hash(self, file_path: str) -> str:
        """Compute SHA256 hash of file."""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()


class RsyncPusher:
    """Push files using rsync."""

    def __init__(self, target: str, ssh_key: Optional[str] = None):
        self.target = target  # user@host:/path
        self.ssh_key = ssh_key

    def push(self, local_path: str, remote_subpath: str = "") -> Dict:
        """Push file or directory via rsync."""
        remote_path = f"{self.target}/{remote_subpath}" if remote_subpath else self.target

        cmd = ["rsync", "-avz", "--progress"]

        if self.ssh_key:
            cmd.extend(["-e", f"ssh -i {self.ssh_key}"])

        cmd.extend([local_path, remote_path])

        logger.info(f"Running: {' '.join(cmd)}")

        start_time = time.time()

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            elapsed = time.time() - start_time

            return {
                "success": True,
                "message": "Transfer completed",
                "elapsed_seconds": elapsed,
                "output": result.stdout,
            }
        except subprocess.CalledProcessError as e:
            return {
                "success": False,
                "message": f"rsync failed: {e.stderr}",
                "output": e.stdout,
            }


class S3Pusher:
    """Push files to S3-compatible storage."""

    def __init__(self, bucket: str, endpoint: Optional[str] = None,
                 access_key: Optional[str] = None, secret_key: Optional[str] = None):
        self.bucket = bucket
        self.endpoint = endpoint

        try:
            import boto3
            if endpoint:
                self.client = boto3.client(
                    's3',
                    endpoint_url=endpoint,
                    aws_access_key_id=access_key,
                    aws_secret_access_key=secret_key,
                )
            else:
                self.client = boto3.client('s3')
        except ImportError:
            raise ImportError("boto3 required for S3 push. Install with: pip install boto3")

    def push(self, local_path: str, s3_key: str, callback: Optional[callable] = None) -> Dict:
        """Upload file to S3."""
        file_size = Path(local_path).stat().st_size

        class ProgressCallback:
            def __init__(self, total, cb):
                self.total = total
                self.uploaded = 0
                self.cb = cb

            def __call__(self, bytes_amount):
                self.uploaded += bytes_amount
                if self.cb:
                    self.cb({
                        "bytes_uploaded": self.uploaded,
                        "total_bytes": self.total,
                        "progress": self.uploaded / self.total,
                    })

        start_time = time.time()

        try:
            self.client.upload_file(
                local_path,
                self.bucket,
                s3_key,
                Callback=ProgressCallback(file_size, callback) if callback else None,
            )
            elapsed = time.time() - start_time

            return {
                "success": True,
                "message": "Upload completed",
                "s3_uri": f"s3://{self.bucket}/{s3_key}",
                "elapsed_seconds": elapsed,
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"S3 upload failed: {str(e)}",
            }


class PushService:
    """Main push service for syncing to viewer server."""

    def __init__(self, config: 'PushConfig'):
        self.config = config
        self.job_queue: Queue = Queue()
        self.results: Dict[str, PushResult] = {}
        self._running = False
        self._worker = None

        # Initialize pusher based on method
        if config.method == "api":
            self.uploader = ChunkedUploader(
                config.viewer_server_url,
                config.api_key,
                config.chunk_size_mb
            )
        elif config.method == "rsync":
            self.uploader = RsyncPusher(config.rsync_target)
        elif config.method == "s3":
            self.uploader = S3Pusher(config.s3_bucket)
        else:
            raise ValueError(f"Unknown push method: {config.method}")

        logger.info(f"PushService initialized with method: {config.method}")

    def start(self):
        """Start the push service worker."""
        if self._running:
            return

        self._running = True
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
        logger.info("PushService started")

    def stop(self):
        """Stop the push service."""
        self._running = False
        if self._worker:
            self._worker.join(timeout=10)
        logger.info("PushService stopped")

    def queue_push(self, job: PushJob) -> str:
        """Queue a push job."""
        self.results[job.job_id] = PushResult(
            job_id=job.job_id,
            success=False,
            message="Queued",
        )
        self.job_queue.put(job)
        logger.info(f"Queued push job: {job.job_id}")
        return job.job_id

    def get_status(self, job_id: str) -> Optional[PushResult]:
        """Get status of a push job."""
        return self.results.get(job_id)

    def _worker_loop(self):
        """Worker thread main loop."""
        while self._running:
            try:
                job = self.job_queue.get(timeout=1)
            except Empty:
                continue

            logger.info(f"Processing push job: {job.job_id}")

            start_time = time.time()

            try:
                result = self._push_job(job)
                result.transfer_time_seconds = time.time() - start_time
                self.results[job.job_id] = result
            except Exception as e:
                logger.error(f"Push job {job.job_id} failed: {e}")
                self.results[job.job_id] = PushResult(
                    job_id=job.job_id,
                    success=False,
                    message=str(e),
                    transfer_time_seconds=time.time() - start_time,
                )

    def _push_job(self, job: PushJob) -> PushResult:
        """Execute a push job."""
        bytes_transferred = 0

        if self.config.method == "api":
            # Upload video
            video_result = self.uploader.upload_file(
                job.video_path,
                Path(job.video_path).name,
                job.session_id,
            )

            if "error" in video_result:
                return PushResult(
                    job_id=job.job_id,
                    success=False,
                    message=f"Video upload failed: {video_result.get('error')}",
                )

            bytes_transferred += Path(job.video_path).stat().st_size

            # Upload metadata
            metadata_result = self.uploader.upload_file(
                job.metadata_path,
                Path(job.metadata_path).name,
                job.session_id,
            )

            bytes_transferred += Path(job.metadata_path).stat().st_size

            # Upload thumbnail if present
            if job.thumbnail_path and Path(job.thumbnail_path).exists():
                self.uploader.upload_file(
                    job.thumbnail_path,
                    Path(job.thumbnail_path).name,
                    job.session_id,
                )
                bytes_transferred += Path(job.thumbnail_path).stat().st_size

            # Notify viewer server that upload is complete
            self._notify_complete(job.session_id)

            return PushResult(
                job_id=job.job_id,
                success=True,
                message="Upload completed",
                remote_url=f"{self.config.viewer_server_url}/watch/{job.session_id}",
                bytes_transferred=bytes_transferred,
            )

        elif self.config.method == "rsync":
            # Create session directory structure
            session_dir = f"sessions/{job.session_id}"

            # Push video
            video_result = self.uploader.push(job.video_path, f"{session_dir}/")
            if not video_result["success"]:
                return PushResult(
                    job_id=job.job_id,
                    success=False,
                    message=video_result["message"],
                )

            bytes_transferred += Path(job.video_path).stat().st_size

            # Push metadata
            self.uploader.push(job.metadata_path, f"{session_dir}/")
            bytes_transferred += Path(job.metadata_path).stat().st_size

            # Push thumbnail
            if job.thumbnail_path and Path(job.thumbnail_path).exists():
                self.uploader.push(job.thumbnail_path, f"{session_dir}/")
                bytes_transferred += Path(job.thumbnail_path).stat().st_size

            return PushResult(
                job_id=job.job_id,
                success=True,
                message="rsync completed",
                bytes_transferred=bytes_transferred,
            )

        elif self.config.method == "s3":
            # Upload to S3
            s3_prefix = f"sessions/{job.session_id}"

            video_result = self.uploader.push(
                job.video_path,
                f"{s3_prefix}/{Path(job.video_path).name}"
            )
            if not video_result["success"]:
                return PushResult(
                    job_id=job.job_id,
                    success=False,
                    message=video_result["message"],
                )

            bytes_transferred += Path(job.video_path).stat().st_size

            self.uploader.push(
                job.metadata_path,
                f"{s3_prefix}/{Path(job.metadata_path).name}"
            )
            bytes_transferred += Path(job.metadata_path).stat().st_size

            if job.thumbnail_path and Path(job.thumbnail_path).exists():
                self.uploader.push(
                    job.thumbnail_path,
                    f"{s3_prefix}/{Path(job.thumbnail_path).name}"
                )
                bytes_transferred += Path(job.thumbnail_path).stat().st_size

            return PushResult(
                job_id=job.job_id,
                success=True,
                message="S3 upload completed",
                remote_url=video_result.get("s3_uri"),
                bytes_transferred=bytes_transferred,
            )

        return PushResult(
            job_id=job.job_id,
            success=False,
            message="Unknown push method",
        )

    def _notify_complete(self, session_id: str):
        """Notify viewer server that a session upload is complete."""
        if self.config.method != "api":
            return

        try:
            response = requests.post(
                f"{self.config.viewer_server_url}/api/sessions/{session_id}/ready",
                headers={"Authorization": f"Bearer {self.config.api_key}"},
                json={"session_id": session_id},
                timeout=30,
            )
            response.raise_for_status()
            logger.info(f"Notified viewer server: session {session_id} ready")
        except Exception as e:
            logger.error(f"Failed to notify viewer server: {e}")


class SyncManager:
    """Manages synchronization state between processing and viewer servers."""

    def __init__(self, push_service: PushService, state_file: str = "sync_state.json"):
        self.push_service = push_service
        self.state_file = Path(state_file)
        self.state = self._load_state()

    def _load_state(self) -> Dict:
        """Load sync state from file."""
        if self.state_file.exists():
            with open(self.state_file) as f:
                return json.load(f)
        return {"synced_sessions": [], "pending_sessions": []}

    def _save_state(self):
        """Save sync state to file."""
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)

    def mark_for_sync(self, session_id: str, video_path: str,
                      metadata_path: str, thumbnail_path: Optional[str] = None):
        """Mark a session for syncing."""
        if session_id not in self.state["pending_sessions"]:
            self.state["pending_sessions"].append({
                "session_id": session_id,
                "video_path": video_path,
                "metadata_path": metadata_path,
                "thumbnail_path": thumbnail_path,
                "queued_at": time.time(),
            })
            self._save_state()

    def sync_pending(self):
        """Sync all pending sessions."""
        for session_data in list(self.state["pending_sessions"]):
            job = PushJob(
                job_id=f"sync_{session_data['session_id']}_{int(time.time())}",
                session_id=session_data["session_id"],
                video_path=session_data["video_path"],
                metadata_path=session_data["metadata_path"],
                thumbnail_path=session_data.get("thumbnail_path"),
            )

            self.push_service.queue_push(job)

            # Move to syncing state
            self.state["pending_sessions"].remove(session_data)
            self._save_state()

    def mark_synced(self, session_id: str):
        """Mark a session as successfully synced."""
        if session_id not in self.state["synced_sessions"]:
            self.state["synced_sessions"].append(session_id)
            self._save_state()

    def is_synced(self, session_id: str) -> bool:
        """Check if a session is synced."""
        return session_id in self.state["synced_sessions"]
