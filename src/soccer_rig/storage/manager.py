"""
Storage manager for recordings and manifests.

Handles:
- Recording file management
- Manifest tracking
- Checksum verification
- Auto-cleanup of offloaded files
"""

import os
import json
import hashlib
import shutil
import logging
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class StorageManager:
    """
    Manages recording storage and cleanup.

    Features:
    - List/get/delete recordings
    - Checksum verification for offload confirmation
    - Automatic cleanup based on policies
    - Disk space monitoring
    """

    def __init__(self, config):
        """
        Initialize storage manager.

        Args:
            config: Configuration object with storage settings
        """
        self.config = config
        self._lock = threading.Lock()

        # Ensure directories exist
        self._init_directories()

        # Start cleanup monitor if enabled
        if config.storage.auto_delete_offloaded:
            self._start_cleanup_monitor()

    def _init_directories(self) -> None:
        """Create storage directories if they don't exist."""
        recordings_path = Path(self.config.storage.recordings_path)
        manifests_path = Path(self.config.storage.manifests_path)

        recordings_path.mkdir(parents=True, exist_ok=True)
        manifests_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"Storage initialized: {recordings_path}")

    def get_status(self) -> Dict[str, Any]:
        """Get storage status and metrics."""
        recordings_path = Path(self.config.storage.recordings_path)

        try:
            # Get disk usage
            disk_usage = shutil.disk_usage(recordings_path)
            free_gb = disk_usage.free / (1024 ** 3)
            total_gb = disk_usage.total / (1024 ** 3)
            used_gb = disk_usage.used / (1024 ** 3)

            # Count recordings
            recordings = list(recordings_path.glob("*.mp4"))
            manifests = list(Path(self.config.storage.manifests_path).glob("*.json"))

            # Calculate total recording size
            total_recording_size = sum(r.stat().st_size for r in recordings)
            total_recording_gb = total_recording_size / (1024 ** 3)

            # Estimate recording time remaining at current bitrate
            bitrate_mbps = self.config.camera.bitrate_mbps
            bytes_per_second = (bitrate_mbps * 1_000_000) / 8
            remaining_seconds = (free_gb * 1024 ** 3) / bytes_per_second
            remaining_minutes = remaining_seconds / 60

            # Count offloaded
            offloaded_count = sum(
                1 for m in manifests
                if self._is_manifest_offloaded(m)
            )

            return {
                "path": str(recordings_path),
                "total_gb": round(total_gb, 2),
                "used_gb": round(used_gb, 2),
                "free_gb": round(free_gb, 2),
                "free_percent": round((free_gb / total_gb) * 100, 1),
                "recording_count": len(recordings),
                "recording_size_gb": round(total_recording_gb, 2),
                "offloaded_count": offloaded_count,
                "estimated_recording_minutes": round(remaining_minutes, 0),
                "min_free_space_gb": self.config.storage.min_free_space_gb,
                "low_space_warning": free_gb < self.config.storage.min_free_space_gb,
            }
        except Exception as e:
            logger.error(f"Error getting storage status: {e}")
            return {
                "error": str(e),
                "path": str(recordings_path),
            }

    def _is_manifest_offloaded(self, manifest_path: Path) -> bool:
        """Check if a manifest indicates the recording is offloaded."""
        try:
            with open(manifest_path, "r") as f:
                data = json.load(f)
                return data.get("offloaded", False)
        except Exception:
            return False

    def list_recordings(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        List all recordings with their metadata.

        Args:
            filters: Optional filters (offloaded, session_id)

        Returns:
            List of recording info dicts
        """
        recordings = []
        recordings_path = Path(self.config.storage.recordings_path)
        manifests_path = Path(self.config.storage.manifests_path)

        filters = filters or {}

        for video_file in sorted(recordings_path.glob("*.mp4"), key=lambda x: x.stat().st_mtime, reverse=True):
            # Find corresponding manifest
            manifest_name = video_file.stem + ".json"

            # Try to find manifest with matching session/camera
            manifest_data = self._find_manifest_for_video(video_file, manifests_path)

            recording_info = {
                "id": video_file.stem,
                "filename": video_file.name,
                "path": str(video_file),
                "size_bytes": video_file.stat().st_size,
                "size_mb": round(video_file.stat().st_size / (1024 * 1024), 2),
                "created": datetime.fromtimestamp(video_file.stat().st_ctime).isoformat(),
                "modified": datetime.fromtimestamp(video_file.stat().st_mtime).isoformat(),
            }

            if manifest_data:
                recording_info.update({
                    "session_id": manifest_data.get("session_id"),
                    "camera_id": manifest_data.get("camera_id"),
                    "duration_sec": manifest_data.get("duration_sec"),
                    "resolution": manifest_data.get("resolution"),
                    "fps": manifest_data.get("fps"),
                    "codec": manifest_data.get("codec"),
                    "offloaded": manifest_data.get("offloaded", False),
                    "checksum": manifest_data.get("checksum"),
                })
            else:
                recording_info["offloaded"] = False

            # Apply filters
            if "offloaded" in filters:
                if recording_info.get("offloaded") != filters["offloaded"]:
                    continue

            if "session_id" in filters:
                if recording_info.get("session_id") != filters["session_id"]:
                    continue

            recordings.append(recording_info)

        return recordings

    def _find_manifest_for_video(self, video_file: Path, manifests_path: Path) -> Optional[Dict]:
        """Find and load manifest for a video file."""
        # Try direct name match first
        for pattern in [
            video_file.stem + ".json",
            "*" + video_file.stem.split("_", 1)[-1] + ".json" if "_" in video_file.stem else None,
        ]:
            if pattern:
                for manifest_file in manifests_path.glob(pattern):
                    try:
                        with open(manifest_file, "r") as f:
                            data = json.load(f)
                            if data.get("file_name") == video_file.name:
                                return data
                    except Exception:
                        continue

        # Search all manifests
        for manifest_file in manifests_path.glob("*.json"):
            try:
                with open(manifest_file, "r") as f:
                    data = json.load(f)
                    if data.get("file_name") == video_file.name:
                        return data
            except Exception:
                continue

        return None

    def get_recording(self, recording_id: str) -> Optional[Dict[str, Any]]:
        """Get details of a specific recording."""
        recordings = self.list_recordings()
        for rec in recordings:
            if rec["id"] == recording_id:
                return rec
        return None

    def confirm_offload(
        self,
        session_id: str,
        camera_id: str,
        filename: str,
        checksum_algo: str,
        checksum_value: str
    ) -> Dict[str, Any]:
        """
        Confirm successful offload by verifying checksum.

        Args:
            session_id: Session identifier
            camera_id: Camera identifier
            filename: Recording filename
            checksum_algo: Checksum algorithm (sha256)
            checksum_value: Expected checksum value

        Returns:
            Result dict with success status
        """
        with self._lock:
            recordings_path = Path(self.config.storage.recordings_path)
            manifests_path = Path(self.config.storage.manifests_path)

            # Find the video file
            video_file = recordings_path / filename
            if not video_file.exists():
                return {
                    "success": False,
                    "error": f"File not found: {filename}"
                }

            # Verify checksum
            if checksum_algo.lower() != "sha256":
                return {
                    "success": False,
                    "error": f"Unsupported checksum algorithm: {checksum_algo}"
                }

            actual_checksum = self._calculate_checksum(video_file)
            if actual_checksum.lower() != checksum_value.lower():
                return {
                    "success": False,
                    "error": "Checksum mismatch",
                    "expected": checksum_value,
                    "actual": actual_checksum,
                }

            # Find and update manifest
            manifest_file = manifests_path / f"{session_id}_{camera_id}.json"
            if manifest_file.exists():
                try:
                    with open(manifest_file, "r") as f:
                        manifest_data = json.load(f)

                    manifest_data["offloaded"] = True
                    manifest_data["offload_confirmed_at"] = datetime.now().isoformat()

                    with open(manifest_file, "w") as f:
                        json.dump(manifest_data, f, indent=2)

                except Exception as e:
                    logger.error(f"Error updating manifest: {e}")

            # Auto-delete if configured
            if self.config.storage.delete_after_confirm:
                self._delete_recording_files(video_file, manifest_file)
                return {
                    "success": True,
                    "message": "Offload confirmed and file deleted",
                    "deleted": True,
                }

            return {
                "success": True,
                "message": "Offload confirmed",
                "deleted": False,
            }

    def _calculate_checksum(self, file_path: Path) -> str:
        """Calculate SHA-256 checksum of a file."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def delete_recording(self, recording_id: str) -> Dict[str, Any]:
        """Delete a specific recording and its manifest."""
        with self._lock:
            recordings_path = Path(self.config.storage.recordings_path)
            manifests_path = Path(self.config.storage.manifests_path)

            # Find video file
            video_file = None
            for ext in [".mp4", ".mkv"]:
                candidate = recordings_path / f"{recording_id}{ext}"
                if candidate.exists():
                    video_file = candidate
                    break

            if not video_file:
                return {
                    "success": False,
                    "error": f"Recording not found: {recording_id}"
                }

            # Find manifest
            manifest_file = None
            for mf in manifests_path.glob("*.json"):
                try:
                    with open(mf, "r") as f:
                        data = json.load(f)
                        if data.get("file_name") == video_file.name:
                            manifest_file = mf
                            break
                except Exception:
                    continue

            # Delete files
            deleted_files = self._delete_recording_files(video_file, manifest_file)

            return {
                "success": True,
                "deleted_files": deleted_files,
            }

    def _delete_recording_files(self, video_file: Optional[Path], manifest_file: Optional[Path]) -> List[str]:
        """Delete recording and manifest files."""
        deleted = []

        if video_file and video_file.exists():
            try:
                video_file.unlink()
                deleted.append(str(video_file))
                logger.info(f"Deleted recording: {video_file}")
            except Exception as e:
                logger.error(f"Error deleting {video_file}: {e}")

        if manifest_file and manifest_file.exists():
            try:
                manifest_file.unlink()
                deleted.append(str(manifest_file))
                logger.info(f"Deleted manifest: {manifest_file}")
            except Exception as e:
                logger.error(f"Error deleting {manifest_file}: {e}")

        return deleted

    def cleanup_offloaded(self) -> Dict[str, Any]:
        """Delete all offloaded recordings."""
        with self._lock:
            deleted_count = 0
            freed_bytes = 0

            recordings = self.list_recordings({"offloaded": True})

            for rec in recordings:
                video_path = Path(rec["path"])
                if video_path.exists():
                    freed_bytes += video_path.stat().st_size

                result = self.delete_recording(rec["id"])
                if result.get("success"):
                    deleted_count += 1

            return {
                "success": True,
                "deleted_count": deleted_count,
                "freed_mb": round(freed_bytes / (1024 * 1024), 2),
            }

    def _start_cleanup_monitor(self) -> None:
        """Start background thread to monitor and cleanup disk space."""
        def monitor_loop():
            import time
            while True:
                try:
                    self._check_disk_space_cleanup()
                except Exception as e:
                    logger.error(f"Cleanup monitor error: {e}")
                time.sleep(300)  # Check every 5 minutes

        thread = threading.Thread(target=monitor_loop, daemon=True)
        thread.start()
        logger.info("Storage cleanup monitor started")

    def _check_disk_space_cleanup(self) -> None:
        """Check disk space and cleanup if necessary."""
        status = self.get_status()

        if status.get("low_space_warning"):
            logger.warning(
                f"Low disk space: {status.get('free_gb', 0):.1f}GB free"
            )

            # Delete oldest offloaded files
            offloaded = self.list_recordings({"offloaded": True})
            if offloaded:
                # Sort by creation time (oldest first)
                offloaded.sort(key=lambda x: x.get("created", ""))

                # Delete oldest until we have enough space
                for rec in offloaded:
                    self.delete_recording(rec["id"])
                    logger.info(f"Auto-deleted offloaded recording: {rec['id']}")

                    # Check if we have enough space now
                    new_status = self.get_status()
                    if not new_status.get("low_space_warning"):
                        break

    def get_recording_path(self, filename: str) -> Optional[Path]:
        """Get full path to a recording file."""
        path = Path(self.config.storage.recordings_path) / filename
        return path if path.exists() else None

    def get_manifest_path(self, filename: str) -> Optional[Path]:
        """Get full path to a manifest file."""
        path = Path(self.config.storage.manifests_path) / filename
        return path if path.exists() else None
