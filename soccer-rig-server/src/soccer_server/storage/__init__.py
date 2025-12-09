"""
Storage management for Soccer Rig Server.

Handles:
- Receiving uploads from Pi nodes
- Organizing recordings by session/game
- Checksum verification
- Storage cleanup
"""

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Recording:
    """Represents a single recording file."""
    id: str
    session_id: str
    camera_id: str
    filename: str
    path: Path
    size_bytes: int
    duration_sec: float
    checksum_sha256: str
    uploaded_at: datetime
    manifest: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "camera_id": self.camera_id,
            "filename": self.filename,
            "path": str(self.path),
            "size_bytes": self.size_bytes,
            "size_mb": round(self.size_bytes / (1024 * 1024), 2),
            "duration_sec": self.duration_sec,
            "duration_min": round(self.duration_sec / 60, 1),
            "checksum_sha256": self.checksum_sha256,
            "uploaded_at": self.uploaded_at.isoformat(),
            "manifest": self.manifest,
        }


@dataclass
class Session:
    """Represents a recording session (game)."""
    id: str
    name: str
    created_at: datetime
    recordings: Dict[str, Recording]  # camera_id -> Recording
    stitched: bool = False
    stitched_path: Optional[Path] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at.isoformat(),
            "recordings": {k: v.to_dict() for k, v in self.recordings.items()},
            "recording_count": len(self.recordings),
            "cameras": list(self.recordings.keys()),
            "complete": len(self.recordings) == 3,  # All 3 cameras
            "stitched": self.stitched,
            "stitched_path": str(self.stitched_path) if self.stitched_path else None,
            "total_size_mb": sum(r.size_bytes for r in self.recordings.values()) / (1024 * 1024),
        }


class StorageManager:
    """
    Manages server-side storage of recordings.

    Directory structure:
    /base_path/
        sessions/
            SESSION_ID/
                CAM_L.mp4
                CAM_L.json (manifest)
                CAM_C.mp4
                CAM_C.json
                CAM_R.mp4
                CAM_R.json
                stitched.mp4 (if processed)
                session.json (session metadata)
        temp/
            (upload chunks)
    """

    def __init__(self, config):
        self.config = config
        self.base_path = Path(config.storage.base_path)
        self.temp_path = Path(config.storage.temp_path)
        self.sessions_path = self.base_path / "sessions"

        # Ensure directories exist
        self.sessions_path.mkdir(parents=True, exist_ok=True)
        self.temp_path.mkdir(parents=True, exist_ok=True)

        # In-memory cache of sessions
        self._sessions: Dict[str, Session] = {}
        self._load_sessions()

    def _load_sessions(self) -> None:
        """Load existing sessions from disk."""
        for session_dir in self.sessions_path.iterdir():
            if session_dir.is_dir():
                try:
                    session = self._load_session(session_dir)
                    if session:
                        self._sessions[session.id] = session
                except Exception as e:
                    logger.error(f"Failed to load session {session_dir}: {e}")

        logger.info(f"Loaded {len(self._sessions)} sessions")

    def _load_session(self, session_dir: Path) -> Optional[Session]:
        """Load a single session from disk."""
        session_meta_path = session_dir / "session.json"

        if session_meta_path.exists():
            with open(session_meta_path) as f:
                meta = json.load(f)
        else:
            meta = {
                "id": session_dir.name,
                "name": session_dir.name,
                "created_at": datetime.fromtimestamp(
                    session_dir.stat().st_mtime
                ).isoformat()
            }

        recordings = {}
        for manifest_file in session_dir.glob("*.json"):
            if manifest_file.name in ("session.json", "stitched.json"):
                continue

            camera_id = manifest_file.stem
            video_file = session_dir / f"{camera_id}.mp4"

            if video_file.exists():
                with open(manifest_file) as f:
                    manifest = json.load(f)

                recordings[camera_id] = Recording(
                    id=f"{session_dir.name}_{camera_id}",
                    session_id=session_dir.name,
                    camera_id=camera_id,
                    filename=video_file.name,
                    path=video_file,
                    size_bytes=video_file.stat().st_size,
                    duration_sec=manifest.get("duration_sec", 0),
                    checksum_sha256=manifest.get("checksum", {}).get("value", ""),
                    uploaded_at=datetime.fromisoformat(
                        manifest.get("uploaded_at", meta["created_at"])
                    ),
                    manifest=manifest,
                )

        stitched_path = session_dir / "stitched.mp4"

        return Session(
            id=session_dir.name,
            name=meta.get("name", session_dir.name),
            created_at=datetime.fromisoformat(meta["created_at"]),
            recordings=recordings,
            stitched=stitched_path.exists(),
            stitched_path=stitched_path if stitched_path.exists() else None,
        )

    def receive_upload(
        self,
        session_id: str,
        camera_id: str,
        file_data,
        manifest: Dict[str, Any],
        expected_checksum: str
    ) -> Dict[str, Any]:
        """
        Receive an uploaded recording from a Pi node.

        Args:
            session_id: Session identifier
            camera_id: Camera ID (CAM_L, CAM_C, CAM_R)
            file_data: File-like object with video data
            manifest: Recording manifest from Pi
            expected_checksum: SHA-256 checksum to verify

        Returns:
            Dict with success status and details
        """
        session_dir = self.sessions_path / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        # Save to temp first
        temp_file = self.temp_path / f"{session_id}_{camera_id}_{datetime.now().timestamp()}.mp4"

        try:
            # Stream to temp file and calculate checksum
            sha256 = hashlib.sha256()
            total_bytes = 0

            with open(temp_file, "wb") as f:
                while True:
                    chunk = file_data.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
                    sha256.update(chunk)
                    total_bytes += len(chunk)

            calculated_checksum = sha256.hexdigest()

            # Verify checksum
            if calculated_checksum != expected_checksum:
                temp_file.unlink()
                return {
                    "success": False,
                    "error": "Checksum mismatch",
                    "expected": expected_checksum,
                    "calculated": calculated_checksum,
                }

            # Move to final location
            final_path = session_dir / f"{camera_id}.mp4"
            shutil.move(str(temp_file), str(final_path))

            # Save manifest
            manifest["uploaded_at"] = datetime.now().isoformat()
            manifest["server_checksum"] = calculated_checksum
            manifest_path = session_dir / f"{camera_id}.json"
            with open(manifest_path, "w") as f:
                json.dump(manifest, f, indent=2)

            # Update session metadata
            self._update_session_meta(session_id)

            # Create recording object
            recording = Recording(
                id=f"{session_id}_{camera_id}",
                session_id=session_id,
                camera_id=camera_id,
                filename=final_path.name,
                path=final_path,
                size_bytes=total_bytes,
                duration_sec=manifest.get("duration_sec", 0),
                checksum_sha256=calculated_checksum,
                uploaded_at=datetime.now(),
                manifest=manifest,
            )

            # Update cache
            if session_id not in self._sessions:
                self._sessions[session_id] = Session(
                    id=session_id,
                    name=manifest.get("session_name", session_id),
                    created_at=datetime.now(),
                    recordings={},
                )
            self._sessions[session_id].recordings[camera_id] = recording

            logger.info(f"Received {camera_id} for session {session_id}: {total_bytes} bytes")

            return {
                "success": True,
                "recording_id": recording.id,
                "session_id": session_id,
                "camera_id": camera_id,
                "size_bytes": total_bytes,
                "checksum_verified": True,
            }

        except Exception as e:
            logger.error(f"Upload failed: {e}")
            if temp_file.exists():
                temp_file.unlink()
            return {
                "success": False,
                "error": str(e),
            }

    def _update_session_meta(self, session_id: str) -> None:
        """Update session metadata file."""
        session_dir = self.sessions_path / session_id
        meta_path = session_dir / "session.json"

        existing = {}
        if meta_path.exists():
            with open(meta_path) as f:
                existing = json.load(f)

        existing.update({
            "id": session_id,
            "updated_at": datetime.now().isoformat(),
        })

        if "created_at" not in existing:
            existing["created_at"] = datetime.now().isoformat()

        with open(meta_path, "w") as f:
            json.dump(existing, f, indent=2)

    def get_session(self, session_id: str) -> Optional[Session]:
        """Get a session by ID."""
        return self._sessions.get(session_id)

    def list_sessions(
        self,
        limit: int = 50,
        offset: int = 0,
        complete_only: bool = False
    ) -> List[Session]:
        """List all sessions."""
        sessions = sorted(
            self._sessions.values(),
            key=lambda s: s.created_at,
            reverse=True
        )

        if complete_only:
            sessions = [s for s in sessions if len(s.recordings) == 3]

        return sessions[offset:offset + limit]

    def get_recording(self, session_id: str, camera_id: str) -> Optional[Recording]:
        """Get a specific recording."""
        session = self._sessions.get(session_id)
        if session:
            return session.recordings.get(camera_id)
        return None

    def delete_session(self, session_id: str) -> Dict[str, Any]:
        """Delete a session and all its recordings."""
        session = self._sessions.get(session_id)
        if not session:
            return {"success": False, "error": "Session not found"}

        session_dir = self.sessions_path / session_id

        try:
            shutil.rmtree(session_dir)
            del self._sessions[session_id]
            logger.info(f"Deleted session {session_id}")
            return {"success": True, "session_id": session_id}
        except Exception as e:
            logger.error(f"Failed to delete session: {e}")
            return {"success": False, "error": str(e)}

    def get_storage_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        total_size = 0
        recording_count = 0
        session_count = len(self._sessions)
        complete_sessions = 0

        for session in self._sessions.values():
            if len(session.recordings) == 3:
                complete_sessions += 1
            for recording in session.recordings.values():
                total_size += recording.size_bytes
                recording_count += 1

        # Disk usage
        import shutil as sh
        total_disk, used_disk, free_disk = sh.disk_usage(self.base_path)

        return {
            "session_count": session_count,
            "complete_sessions": complete_sessions,
            "recording_count": recording_count,
            "total_size_gb": round(total_size / (1024**3), 2),
            "disk_total_gb": round(total_disk / (1024**3), 2),
            "disk_used_gb": round(used_disk / (1024**3), 2),
            "disk_free_gb": round(free_disk / (1024**3), 2),
        }

    def confirm_offload(self, session_id: str, camera_id: str) -> Dict[str, Any]:
        """
        Confirm that a recording was successfully offloaded.

        Returns confirmation that can be sent back to Pi node.
        """
        recording = self.get_recording(session_id, camera_id)
        if not recording:
            return {
                "success": False,
                "error": "Recording not found"
            }

        return {
            "success": True,
            "session_id": session_id,
            "camera_id": camera_id,
            "checksum_sha256": recording.checksum_sha256,
            "size_bytes": recording.size_bytes,
            "confirmed_at": datetime.now().isoformat(),
        }
