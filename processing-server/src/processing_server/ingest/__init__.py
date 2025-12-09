"""
Ingest server for receiving recordings from Pi camera nodes.

Receives chunked uploads with checksum verification and
queues complete sessions for processing.
"""

import os
import json
import hashlib
import shutil
import logging
import threading
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Dict, Optional, List
from flask import Flask, request, jsonify

logger = logging.getLogger(__name__)


@dataclass
class UploadSession:
    """Tracks an in-progress upload."""
    upload_id: str
    session_id: str
    node_id: str
    filename: str
    file_size: int
    chunk_size: int
    chunks_received: List[int] = field(default_factory=list)
    expected_hash: Optional[str] = None
    started_at: float = 0
    temp_path: Optional[str] = None


@dataclass
class RecordingSession:
    """A complete recording session from all nodes."""
    session_id: str
    created_at: datetime
    recordings: Dict[str, str] = field(default_factory=dict)  # node_id -> file_path
    manifest: Optional[Dict] = None
    status: str = "incomplete"  # incomplete, ready, processing, done


class IngestServer:
    """Server for receiving Pi node uploads."""

    def __init__(self, config: 'ServerConfig', storage_config: 'StorageConfig'):
        self.config = config
        self.storage = storage_config

        # Ensure directories exist
        Path(storage_config.incoming_path).mkdir(parents=True, exist_ok=True)
        Path(storage_config.processing_path).mkdir(parents=True, exist_ok=True)
        Path(storage_config.output_path).mkdir(parents=True, exist_ok=True)

        # Active uploads
        self.uploads: Dict[str, UploadSession] = {}
        self.sessions: Dict[str, RecordingSession] = {}
        self._lock = threading.Lock()

        # Callback for when session is ready
        self.on_session_ready: Optional[callable] = None

        # Create Flask app
        self.app = Flask(__name__)
        self._setup_routes()

        logger.info(f"IngestServer initialized, incoming: {storage_config.incoming_path}")

    def _setup_routes(self):
        """Setup Flask routes."""

        @self.app.route('/health', methods=['GET'])
        def health():
            return jsonify({"status": "ok"})

        @self.app.route('/api/upload/init', methods=['POST'])
        def init_upload():
            """Initialize a chunked upload."""
            data = request.json

            required = ['node_id', 'session_id', 'filename', 'file_size', 'chunk_size']
            for field_name in required:
                if field_name not in data:
                    return jsonify({"error": f"Missing field: {field_name}"}), 400

            upload_id = f"{data['session_id']}_{data['node_id']}_{int(datetime.now().timestamp())}"

            # Create temp directory
            temp_dir = Path(self.storage.incoming_path) / "uploads" / upload_id
            temp_dir.mkdir(parents=True, exist_ok=True)

            upload = UploadSession(
                upload_id=upload_id,
                session_id=data['session_id'],
                node_id=data['node_id'],
                filename=data['filename'],
                file_size=data['file_size'],
                chunk_size=data['chunk_size'],
                expected_hash=data.get('file_hash'),
                started_at=datetime.now().timestamp(),
                temp_path=str(temp_dir),
            )

            with self._lock:
                self.uploads[upload_id] = upload

            # Check for resume
            existing_chunks = list(temp_dir.glob("chunk_*"))
            resume_chunk = len(existing_chunks) if existing_chunks else 0

            logger.info(f"Upload initialized: {upload_id}, resume from chunk {resume_chunk}")

            return jsonify({
                "upload_id": upload_id,
                "resume_chunk": resume_chunk,
            })

        @self.app.route('/api/upload/chunk', methods=['POST'])
        def upload_chunk():
            """Receive a chunk."""
            upload_id = request.form.get('upload_id')
            chunk_index = int(request.form.get('chunk_index', 0))
            chunk_hash = request.form.get('chunk_hash')

            if upload_id not in self.uploads:
                return jsonify({"error": "Unknown upload_id"}), 404

            upload = self.uploads[upload_id]

            if 'chunk' not in request.files:
                return jsonify({"error": "No chunk data"}), 400

            chunk_data = request.files['chunk'].read()

            # Verify hash
            if chunk_hash:
                actual_hash = hashlib.md5(chunk_data).hexdigest()
                if actual_hash != chunk_hash:
                    return jsonify({"error": "Chunk hash mismatch"}), 400

            # Save chunk
            chunk_path = Path(upload.temp_path) / f"chunk_{chunk_index:06d}"
            with open(chunk_path, 'wb') as f:
                f.write(chunk_data)

            upload.chunks_received.append(chunk_index)

            logger.debug(f"Upload {upload_id}: chunk {chunk_index} received")

            return jsonify({"status": "ok", "chunk_index": chunk_index})

        @self.app.route('/api/upload/finalize', methods=['POST'])
        def finalize_upload():
            """Finalize an upload."""
            data = request.json
            upload_id = data.get('upload_id')

            if upload_id not in self.uploads:
                return jsonify({"error": "Unknown upload_id"}), 404

            upload = self.uploads[upload_id]

            # Assemble file
            temp_dir = Path(upload.temp_path)
            output_dir = Path(self.storage.incoming_path) / upload.session_id
            output_dir.mkdir(parents=True, exist_ok=True)

            output_path = output_dir / upload.filename

            logger.info(f"Assembling upload {upload_id} to {output_path}")

            # Concatenate chunks
            chunk_files = sorted(temp_dir.glob("chunk_*"))
            with open(output_path, 'wb') as out_f:
                for chunk_file in chunk_files:
                    with open(chunk_file, 'rb') as in_f:
                        shutil.copyfileobj(in_f, out_f)

            # Verify hash
            if upload.expected_hash:
                actual_hash = self._compute_hash(str(output_path))
                if actual_hash != upload.expected_hash:
                    os.remove(output_path)
                    return jsonify({"error": "File hash mismatch"}), 400

            # Cleanup temp
            shutil.rmtree(temp_dir, ignore_errors=True)

            # Update session
            self._update_session(upload.session_id, upload.node_id, str(output_path))

            with self._lock:
                del self.uploads[upload_id]

            logger.info(f"Upload {upload_id} finalized: {output_path}")

            return jsonify({
                "status": "ok",
                "path": str(output_path),
            })

        @self.app.route('/api/session/<session_id>/manifest', methods=['POST'])
        def upload_manifest():
            """Upload session manifest with metadata."""
            session_id = request.view_args['session_id']
            manifest = request.json

            if session_id not in self.sessions:
                self.sessions[session_id] = RecordingSession(
                    session_id=session_id,
                    created_at=datetime.now(),
                )

            self.sessions[session_id].manifest = manifest

            # Save manifest to disk
            manifest_path = Path(self.storage.incoming_path) / session_id / "manifest.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            with open(manifest_path, 'w') as f:
                json.dump(manifest, f, indent=2)

            # Check if session is ready
            self._check_session_ready(session_id)

            return jsonify({"status": "ok"})

        @self.app.route('/api/session/<session_id>/status', methods=['GET'])
        def session_status():
            """Get session status."""
            session_id = request.view_args['session_id']

            if session_id not in self.sessions:
                return jsonify({"error": "Session not found"}), 404

            session = self.sessions[session_id]

            return jsonify({
                "session_id": session.session_id,
                "status": session.status,
                "recordings": list(session.recordings.keys()),
                "has_manifest": session.manifest is not None,
            })

        @self.app.route('/api/sessions', methods=['GET'])
        def list_sessions():
            """List all sessions."""
            sessions = []
            for session in self.sessions.values():
                sessions.append({
                    "session_id": session.session_id,
                    "status": session.status,
                    "recordings_count": len(session.recordings),
                    "created_at": session.created_at.isoformat(),
                })
            return jsonify(sessions)

    def _update_session(self, session_id: str, node_id: str, file_path: str):
        """Update session with new recording."""
        with self._lock:
            if session_id not in self.sessions:
                self.sessions[session_id] = RecordingSession(
                    session_id=session_id,
                    created_at=datetime.now(),
                )

            self.sessions[session_id].recordings[node_id] = file_path

        self._check_session_ready(session_id)

    def _check_session_ready(self, session_id: str):
        """Check if session has all required recordings."""
        session = self.sessions.get(session_id)
        if not session:
            return

        # Check if we have all expected recordings
        if session.manifest:
            expected_nodes = set(session.manifest.get('nodes', []))
            received_nodes = set(session.recordings.keys())

            if expected_nodes and expected_nodes <= received_nodes:
                session.status = "ready"
                logger.info(f"Session {session_id} is ready for processing")

                if self.on_session_ready:
                    self.on_session_ready(session_id, session)

        elif len(session.recordings) >= 3:
            # Default: expect 3 cameras
            session.status = "ready"
            logger.info(f"Session {session_id} is ready (3 recordings)")

            if self.on_session_ready:
                self.on_session_ready(session_id, session)

    def _compute_hash(self, file_path: str) -> str:
        """Compute SHA256 hash."""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()

    def get_session(self, session_id: str) -> Optional[RecordingSession]:
        """Get a session by ID."""
        return self.sessions.get(session_id)

    def get_ready_sessions(self) -> List[RecordingSession]:
        """Get all sessions ready for processing."""
        return [s for s in self.sessions.values() if s.status == "ready"]

    def mark_processing(self, session_id: str):
        """Mark session as being processed."""
        if session_id in self.sessions:
            self.sessions[session_id].status = "processing"

    def mark_done(self, session_id: str):
        """Mark session as done."""
        if session_id in self.sessions:
            self.sessions[session_id].status = "done"

    def run(self, host: Optional[str] = None, port: Optional[int] = None):
        """Run the ingest server."""
        host = host or self.config.host
        port = port or self.config.port

        logger.info(f"Starting ingest server on {host}:{port}")
        self.app.run(host=host, port=port, threaded=True)
