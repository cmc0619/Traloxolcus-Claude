"""
Multi-camera coordinator for Soccer Rig.

Handles orchestration across all camera nodes:
- Coordinated start/stop with NTP-synced timing
- Aggregated status collection
- Pre-flight checks
- Session management
"""

import time
import logging
import threading
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Standard camera positions
CAMERA_POSITIONS = {
    "CAM_L": {"position": "left", "order": 0},
    "CAM_C": {"position": "center", "order": 1},
    "CAM_R": {"position": "right", "order": 2},
}


@dataclass
class PeerNode:
    """Represents a peer camera node."""
    camera_id: str
    ip: str
    port: int = 8080
    position: str = ""
    status: str = "unknown"  # unknown, online, offline, recording, error
    last_seen: Optional[datetime] = None
    last_status: Optional[Dict] = None
    manually_configured: bool = False


@dataclass
class Session:
    """Recording session across all cameras."""
    session_id: str
    created_at: datetime
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    cameras: Dict[str, Dict] = field(default_factory=dict)
    status: str = "created"  # created, starting, recording, stopping, completed, failed


class Coordinator:
    """
    Multi-camera coordinator.

    Runs on the master node (CAM_C) and orchestrates all cameras.
    Can also run on any node to provide aggregated view.
    """

    def __init__(self, config, local_recorder=None, local_sync=None, local_storage=None):
        """
        Initialize coordinator.

        Args:
            config: Configuration object
            local_recorder: Local CameraRecorder instance
            local_sync: Local SyncManager instance
            local_storage: Local StorageManager instance
        """
        self.config = config
        self.local_recorder = local_recorder
        self.local_sync = local_sync
        self.local_storage = local_storage
        self.local_camera_id = config.camera.id

        self._peers: Dict[str, PeerNode] = {}
        self._current_session: Optional[Session] = None
        self._sessions: List[Session] = []
        self._lock = threading.Lock()

        # Request timeout for peer communication
        self._timeout = 5

        # Start peer monitoring
        self._monitor_thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        """Start the coordinator."""
        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_peers,
            daemon=True
        )
        self._monitor_thread.start()
        logger.info("Coordinator started")

    def stop(self) -> None:
        """Stop the coordinator."""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2)
        logger.info("Coordinator stopped")

    # =========================================================================
    # Peer Management
    # =========================================================================

    def add_peer(self, camera_id: str, ip: str, port: int = 8080,
                 manual: bool = False) -> Dict[str, Any]:
        """
        Add a peer node.

        Args:
            camera_id: Camera identifier (CAM_L, CAM_C, CAM_R)
            ip: IP address
            port: API port
            manual: Whether manually configured
        """
        with self._lock:
            position = CAMERA_POSITIONS.get(camera_id, {}).get("position", "")

            self._peers[camera_id] = PeerNode(
                camera_id=camera_id,
                ip=ip,
                port=port,
                position=position,
                manually_configured=manual
            )

            logger.info(f"Added peer: {camera_id} at {ip}:{port}")

            return {"success": True, "camera_id": camera_id}

    def remove_peer(self, camera_id: str) -> Dict[str, Any]:
        """Remove a peer node."""
        with self._lock:
            if camera_id in self._peers:
                del self._peers[camera_id]
                return {"success": True}
            return {"success": False, "error": "Peer not found"}

    def update_peer_from_discovery(self, camera_id: str, ip: str,
                                   port: int, position: str) -> None:
        """Update peer info from mDNS discovery."""
        with self._lock:
            if camera_id in self._peers and self._peers[camera_id].manually_configured:
                # Don't overwrite manual config
                return

            self._peers[camera_id] = PeerNode(
                camera_id=camera_id,
                ip=ip,
                port=port,
                position=position,
                manually_configured=False
            )

    def get_peers(self) -> List[Dict[str, Any]]:
        """Get list of all peers including local node."""
        peers = []

        # Add local node
        local_status = self._get_local_status()
        peers.append({
            "camera_id": self.local_camera_id,
            "ip": "localhost",
            "port": self.config.network.web_port,
            "position": self.config.camera.position,
            "status": "recording" if local_status.get("recording", {}).get("is_recording") else "online",
            "is_local": True,
            "is_master": self.config.sync.is_master,
            "details": local_status,
        })

        # Add remote peers
        with self._lock:
            for peer in self._peers.values():
                if peer.camera_id == self.local_camera_id:
                    continue

                peers.append({
                    "camera_id": peer.camera_id,
                    "ip": peer.ip,
                    "port": peer.port,
                    "position": peer.position,
                    "status": peer.status,
                    "is_local": False,
                    "is_master": peer.camera_id == "CAM_C",
                    "last_seen": peer.last_seen.isoformat() if peer.last_seen else None,
                    "details": peer.last_status,
                })

        # Sort by position order
        peers.sort(key=lambda p: CAMERA_POSITIONS.get(p["camera_id"], {}).get("order", 99))

        return peers

    def _monitor_peers(self) -> None:
        """Background thread to monitor peer status."""
        while self._running:
            try:
                self._refresh_peer_status()
            except Exception as e:
                logger.error(f"Peer monitoring error: {e}")
            time.sleep(2)

    def _refresh_peer_status(self) -> None:
        """Refresh status of all peers."""
        with self._lock:
            peers_to_check = list(self._peers.values())

        for peer in peers_to_check:
            try:
                status = self._call_peer(peer, "/status")

                with self._lock:
                    if peer.camera_id in self._peers:
                        self._peers[peer.camera_id].status = (
                            "recording" if status.get("recording", {}).get("is_recording")
                            else "online"
                        )
                        self._peers[peer.camera_id].last_seen = datetime.now()
                        self._peers[peer.camera_id].last_status = status

            except Exception as e:
                with self._lock:
                    if peer.camera_id in self._peers:
                        self._peers[peer.camera_id].status = "offline"

    def _call_peer(self, peer: PeerNode, endpoint: str,
                   method: str = "GET", data: Dict = None) -> Dict:
        """Make API call to a peer node."""
        url = f"http://{peer.ip}:{peer.port}/api/v1{endpoint}"

        if method == "GET":
            response = requests.get(url, timeout=self._timeout)
        else:
            response = requests.post(url, json=data, timeout=self._timeout)

        response.raise_for_status()
        return response.json()

    def _get_local_status(self) -> Dict:
        """Get local node status."""
        if self.local_recorder:
            return self.local_recorder.get_status()
        return {}

    # =========================================================================
    # Coordinated Recording
    # =========================================================================

    def start_all(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Start recording on all cameras with synchronized timing.

        Uses NTP-synced time to ensure all cameras start at the same moment.

        Args:
            session_id: Optional session identifier

        Returns:
            Dict with results from all cameras
        """
        if self._current_session and self._current_session.status == "recording":
            return {
                "success": False,
                "error": "Recording already in progress",
                "session_id": self._current_session.session_id
            }

        # Generate session ID
        if not session_id:
            session_id = f"SESSION_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Create session
        self._current_session = Session(
            session_id=session_id,
            created_at=datetime.now()
        )
        self._current_session.status = "starting"

        # Calculate synchronized start time (2 seconds from now)
        if self.local_sync:
            master_time = self.local_sync.get_master_time()
        else:
            master_time = datetime.now()

        start_time = master_time + timedelta(seconds=2)
        start_time_iso = start_time.isoformat()

        results = {
            "session_id": session_id,
            "scheduled_start": start_time_iso,
            "cameras": {}
        }

        # Collect all nodes to start
        all_nodes = self.get_peers()

        # Send start command to all peers (including scheduling info)
        threads = []

        for node in all_nodes:
            camera_id = node["camera_id"]

            def start_camera(cam_id, node_info):
                try:
                    if node_info["is_local"]:
                        # Start local recorder
                        result = self._start_local(session_id, start_time)
                    else:
                        # Start remote peer
                        peer = self._peers.get(cam_id)
                        if peer:
                            result = self._call_peer(
                                peer,
                                "/record/start",
                                method="POST",
                                data={
                                    "session_id": session_id,
                                    "master_time": start_time_iso,
                                    "scheduled_start": start_time_iso
                                }
                            )
                        else:
                            result = {"success": False, "error": "Peer not found"}

                    results["cameras"][cam_id] = result

                except Exception as e:
                    results["cameras"][cam_id] = {
                        "success": False,
                        "error": str(e)
                    }

            t = threading.Thread(target=start_camera, args=(camera_id, node))
            threads.append(t)
            t.start()

        # Wait for all to complete
        for t in threads:
            t.join(timeout=10)

        # Check results
        all_success = all(
            r.get("success", False)
            for r in results["cameras"].values()
        )

        if all_success:
            self._current_session.status = "recording"
            self._current_session.started_at = start_time
            results["success"] = True
            results["message"] = "All cameras started"
        else:
            self._current_session.status = "failed"
            results["success"] = False
            results["message"] = "Some cameras failed to start"

            # Log failures
            for cam_id, result in results["cameras"].items():
                if not result.get("success"):
                    logger.error(f"Failed to start {cam_id}: {result.get('error')}")

        return results

    def _start_local(self, session_id: str, start_time: datetime) -> Dict:
        """Start local recorder with scheduled time."""
        if not self.local_recorder:
            return {"success": False, "error": "No local recorder"}

        # Wait until scheduled start time
        now = datetime.now()
        wait_time = (start_time - now).total_seconds()

        if wait_time > 0:
            time.sleep(wait_time)

        return self.local_recorder.start_recording(session_id, start_time)

    def stop_all(self) -> Dict[str, Any]:
        """
        Stop recording on all cameras.

        Returns:
            Dict with results from all cameras
        """
        if not self._current_session or self._current_session.status != "recording":
            return {
                "success": False,
                "error": "No recording in progress"
            }

        self._current_session.status = "stopping"

        results = {
            "session_id": self._current_session.session_id,
            "cameras": {}
        }

        all_nodes = self.get_peers()
        threads = []

        for node in all_nodes:
            camera_id = node["camera_id"]

            def stop_camera(cam_id, node_info):
                try:
                    if node_info["is_local"]:
                        if self.local_recorder:
                            result = self.local_recorder.stop_recording()
                        else:
                            result = {"success": False, "error": "No local recorder"}
                    else:
                        peer = self._peers.get(cam_id)
                        if peer:
                            result = self._call_peer(peer, "/record/stop", method="POST")
                        else:
                            result = {"success": False, "error": "Peer not found"}

                    results["cameras"][cam_id] = result

                except Exception as e:
                    results["cameras"][cam_id] = {
                        "success": False,
                        "error": str(e)
                    }

            t = threading.Thread(target=stop_camera, args=(camera_id, node))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=10)

        # Update session
        self._current_session.stopped_at = datetime.now()
        self._current_session.status = "completed"
        self._current_session.cameras = results["cameras"]
        self._sessions.append(self._current_session)

        all_success = all(
            r.get("success", False)
            for r in results["cameras"].values()
        )

        results["success"] = all_success
        results["message"] = "All cameras stopped" if all_success else "Some cameras failed to stop"

        self._current_session = None

        return results

    # =========================================================================
    # Aggregated Status
    # =========================================================================

    def get_aggregated_status(self) -> Dict[str, Any]:
        """
        Get aggregated status from all cameras.

        Returns combined view for dashboard.
        """
        peers = self.get_peers()

        # Aggregate metrics
        total_storage_free_gb = 0
        total_recording_minutes = 0
        all_synced = True
        any_recording = False
        cameras_online = 0
        cameras_total = len(peers)

        camera_statuses = []

        for peer in peers:
            details = peer.get("details", {})

            if peer["status"] in ["online", "recording"]:
                cameras_online += 1

            if peer["status"] == "recording":
                any_recording = True

            storage = details.get("storage", {})
            total_storage_free_gb += storage.get("free_gb", 0)
            total_recording_minutes += storage.get("estimated_recording_minutes", 0)

            sync = details.get("sync", {})
            if not sync.get("within_tolerance", True):
                all_synced = False

            camera_statuses.append({
                "camera_id": peer["camera_id"],
                "position": peer["position"],
                "status": peer["status"],
                "is_local": peer.get("is_local", False),
                "is_master": peer.get("is_master", False),
                "camera": details.get("camera", {}),
                "recording": details.get("recording", {}),
                "storage": storage,
                "sync": sync,
                "system": details.get("system", {}),
            })

        return {
            "timestamp": datetime.now().isoformat(),
            "session": {
                "id": self._current_session.session_id if self._current_session else None,
                "status": self._current_session.status if self._current_session else "idle",
                "started_at": (
                    self._current_session.started_at.isoformat()
                    if self._current_session and self._current_session.started_at
                    else None
                ),
            },
            "summary": {
                "cameras_online": cameras_online,
                "cameras_total": cameras_total,
                "all_online": cameras_online == cameras_total,
                "any_recording": any_recording,
                "all_synced": all_synced,
                "total_storage_free_gb": round(total_storage_free_gb, 1),
                "total_recording_minutes": round(total_recording_minutes / max(cameras_online, 1), 0),
            },
            "cameras": camera_statuses,
        }

    # =========================================================================
    # Pre-flight Checks
    # =========================================================================

    def run_preflight_check(self) -> Dict[str, Any]:
        """
        Run pre-flight checks on all cameras.

        Verifies:
        - All cameras online
        - All cameras detected
        - Time sync within tolerance
        - Sufficient storage
        - Temperature OK
        """
        checks = {
            "passed": True,
            "timestamp": datetime.now().isoformat(),
            "checks": [],
            "cameras": {}
        }

        peers = self.get_peers()

        # Check: All cameras discovered
        expected_cameras = {"CAM_L", "CAM_C", "CAM_R"}
        found_cameras = {p["camera_id"] for p in peers}
        missing = expected_cameras - found_cameras

        checks["checks"].append({
            "name": "all_cameras_discovered",
            "passed": len(missing) == 0,
            "message": f"Missing cameras: {missing}" if missing else "All cameras found",
        })

        if missing:
            checks["passed"] = False

        # Check each camera
        for peer in peers:
            camera_id = peer["camera_id"]
            details = peer.get("details", {})
            camera_checks = []

            # Online check
            is_online = peer["status"] in ["online", "recording"]
            camera_checks.append({
                "name": "online",
                "passed": is_online,
                "message": f"Status: {peer['status']}"
            })

            if not is_online:
                checks["passed"] = False

            # Camera detected
            camera_detected = details.get("camera", {}).get("detected", False)
            camera_checks.append({
                "name": "camera_detected",
                "passed": camera_detected,
                "message": "Camera hardware detected" if camera_detected else "Camera not detected"
            })

            if not camera_detected:
                checks["passed"] = False

            # Time sync
            sync = details.get("sync", {})
            sync_ok = sync.get("within_tolerance", False)
            offset = sync.get("offset_ms", 0)
            camera_checks.append({
                "name": "time_sync",
                "passed": sync_ok,
                "message": f"Offset: {offset:.1f}ms" + (" (OK)" if sync_ok else " (OUT OF SYNC)")
            })

            if not sync_ok:
                checks["passed"] = False

            # Storage
            storage = details.get("storage", {})
            storage_ok = not storage.get("low_space_warning", True)
            free_gb = storage.get("free_gb", 0)
            est_minutes = storage.get("estimated_recording_minutes", 0)
            camera_checks.append({
                "name": "storage",
                "passed": storage_ok,
                "message": f"{free_gb:.1f}GB free (~{est_minutes:.0f} min)"
            })

            if not storage_ok:
                checks["passed"] = False

            # Temperature
            system = details.get("system", {})
            temp = system.get("temperature_c", 0)
            temp_ok = temp < 75
            camera_checks.append({
                "name": "temperature",
                "passed": temp_ok,
                "message": f"{temp:.1f}°C" + (" (OK)" if temp_ok else " (HOT!)")
            })

            if not temp_ok:
                checks["passed"] = False

            checks["cameras"][camera_id] = {
                "position": peer["position"],
                "checks": camera_checks,
                "all_passed": all(c["passed"] for c in camera_checks)
            }

        return checks

    # =========================================================================
    # Session Management
    # =========================================================================

    def get_current_session(self) -> Optional[Dict[str, Any]]:
        """Get current recording session info."""
        if not self._current_session:
            return None

        return {
            "session_id": self._current_session.session_id,
            "status": self._current_session.status,
            "created_at": self._current_session.created_at.isoformat(),
            "started_at": (
                self._current_session.started_at.isoformat()
                if self._current_session.started_at else None
            ),
            "duration_sec": (
                (datetime.now() - self._current_session.started_at).total_seconds()
                if self._current_session.started_at else 0
            ),
        }

    def get_session_history(self) -> List[Dict[str, Any]]:
        """Get list of past sessions."""
        return [
            {
                "session_id": s.session_id,
                "status": s.status,
                "created_at": s.created_at.isoformat(),
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "stopped_at": s.stopped_at.isoformat() if s.stopped_at else None,
                "duration_sec": (
                    (s.stopped_at - s.started_at).total_seconds()
                    if s.started_at and s.stopped_at else 0
                ),
                "cameras": list(s.cameras.keys()),
            }
            for s in reversed(self._sessions[-20:])  # Last 20 sessions
        ]

    # =========================================================================
    # Bulk Operations
    # =========================================================================

    def get_all_recordings(self) -> Dict[str, Any]:
        """Get recordings from all cameras."""
        all_recordings = {
            "total_count": 0,
            "total_size_mb": 0,
            "cameras": {}
        }

        peers = self.get_peers()

        for peer in peers:
            camera_id = peer["camera_id"]

            try:
                if peer["is_local"]:
                    # Get local recordings from storage manager
                    if self.local_storage:
                        recordings = self.local_storage.list_recordings()
                    else:
                        recordings = []
                else:
                    p = self._peers.get(camera_id)
                    if p:
                        result = self._call_peer(p, "/recordings")
                        recordings = result.get("recordings", [])
                    else:
                        recordings = []

                all_recordings["cameras"][camera_id] = recordings
                all_recordings["total_count"] += len(recordings)
                all_recordings["total_size_mb"] += sum(r.get("size_mb", 0) for r in recordings)

            except Exception as e:
                all_recordings["cameras"][camera_id] = {"error": str(e)}

        return all_recordings

    def trigger_sync_all(self) -> Dict[str, Any]:
        """Trigger time sync on all cameras."""
        results = {"cameras": {}}

        peers = self.get_peers()

        for peer in peers:
            camera_id = peer["camera_id"]

            try:
                if peer["is_local"]:
                    if self.local_sync:
                        result = self.local_sync.force_sync()
                    else:
                        result = {"success": False, "error": "No sync manager"}
                else:
                    p = self._peers.get(camera_id)
                    if p:
                        result = self._call_peer(p, "/sync/trigger", method="POST")
                    else:
                        result = {"success": False, "error": "Peer not found"}

                results["cameras"][camera_id] = result

            except Exception as e:
                results["cameras"][camera_id] = {"success": False, "error": str(e)}

        results["success"] = all(
            r.get("success", False) for r in results["cameras"].values()
        )

        return results

    def run_test_all(self) -> Dict[str, Any]:
        """Run test recording on all cameras."""
        results = {"cameras": {}}

        peers = self.get_peers()
        threads = []

        for peer in peers:
            camera_id = peer["camera_id"]

            def run_test(cam_id, node_info):
                try:
                    if node_info["is_local"]:
                        if self.local_recorder:
                            result = self.local_recorder.run_test_recording()
                        else:
                            result = {"passed": False, "errors": ["No recorder"]}
                    else:
                        p = self._peers.get(cam_id)
                        if p:
                            result = self._call_peer(p, "/selftest", method="POST")
                        else:
                            result = {"passed": False, "errors": ["Peer not found"]}

                    results["cameras"][cam_id] = result

                except Exception as e:
                    results["cameras"][cam_id] = {"passed": False, "errors": [str(e)]}

            t = threading.Thread(target=run_test, args=(camera_id, peer))
            threads.append(t)
            t.start()

        # Wait with timeout
        for t in threads:
            t.join(timeout=30)

        results["all_passed"] = all(
            r.get("passed", False) for r in results["cameras"].values()
        )

        return results
