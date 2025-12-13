"""
Simulation camera recorder for testing.

Provides a virtual camera that works without hardware.
Useful for development and testing on non-Pi systems.
"""

import time
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

from soccer_rig.camera.base import (
    BaseCameraRecorder,
    RecordingState,
    CameraStatus,
    register_camera
)

logger = logging.getLogger(__name__)


@register_camera("simulation")
class SimulationCameraRecorder(BaseCameraRecorder):
    """
    Virtual camera for testing without hardware.
    
    Records simulated sessions with metadata but no actual video.
    Useful for testing the full pipeline on dev machines.
    """
    
    def __init__(self, config):
        """Initialize simulation camera."""
        super().__init__(config)
        self._recording_start: Optional[datetime] = None
        
        # Always detects successfully
        self.camera_status.detected = True
        self.camera_status.model = "Simulation Camera v1.0"
        self.camera_status.resolution = (
            f"{config.camera.resolution_width}x{config.camera.resolution_height}"
        )
        self.camera_status.fps = config.camera.fps
        self.camera_status.codec = config.camera.codec
        self.camera_status.bitrate_mbps = config.camera.bitrate_mbps
        
        logger.info("Simulation camera initialized")
    
    def _init_camera(self) -> bool:
        """Initialize the camera (no-op for simulation)."""
        return True
    
    def start_recording(
        self,
        session_id: str,
        master_time: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Start simulated recording."""
        if self.recording_state.is_recording:
            return {"success": False, "error": "Already recording"}
        
        # Create output directory
        recordings_path = Path(self.config.storage.recordings_path)
        recordings_path.mkdir(parents=True, exist_ok=True)
        
        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        camera_id = self.config.camera.id
        filename = f"{session_id}_{camera_id}_{timestamp}_SIM.mp4"
        file_path = recordings_path / filename
        
        # Update state
        self.recording_state = RecordingState(
            is_recording=True,
            session_id=session_id,
            file_path=str(file_path),
            start_time_local=datetime.now(),
            start_time_master=master_time or datetime.now(),
            offset_ms=0.0,
        )
        
        if master_time:
            offset = (datetime.now() - master_time).total_seconds() * 1000
            self.recording_state.offset_ms = offset
        
        self._recording_start = datetime.now()
        
        logger.info(f"[SIMULATION] Recording started: {filename}")
        
        return {
            "success": True,
            "session_id": session_id,
            "file_path": str(file_path),
            "start_time": self.recording_state.start_time_local.isoformat(),
            "simulation": True,
        }
    
    def stop_recording(self) -> Dict[str, Any]:
        """Stop simulated recording."""
        if not self.recording_state.is_recording:
            return {"success": False, "error": "Not recording"}
        
        # Calculate duration
        if self._recording_start:
            duration = (datetime.now() - self._recording_start).total_seconds()
            self.recording_state.duration_sec = duration
        
        self.recording_state.is_recording = False
        
        # Create a dummy file to simulate output
        file_path = Path(self.recording_state.file_path)
        file_path.write_text(f"SIMULATION: {self.recording_state.session_id}")
        
        # Generate manifest
        manifest = self._generate_manifest()
        manifest_path = self._save_manifest(manifest)
        
        logger.info(
            f"[SIMULATION] Recording stopped: {file_path.name} "
            f"({self.recording_state.duration_sec:.1f}s)"
        )
        
        return {
            "success": True,
            "file_path": str(file_path),
            "manifest_path": manifest_path,
            "duration_sec": self.recording_state.duration_sec,
            "simulation": True,
        }
    
    def _generate_manifest(self) -> Dict[str, Any]:
        """Generate session manifest."""
        return {
            "session_id": self.recording_state.session_id,
            "camera_id": self.config.camera.id,
            "camera_position": self.config.camera.position,
            "simulation": True,
            "start_time_local": (
                self.recording_state.start_time_local.isoformat()
                if self.recording_state.start_time_local else None
            ),
            "duration_sec": self.recording_state.duration_sec,
            "resolution": self.camera_status.resolution,
            "fps": self.config.camera.fps,
            "codec": self.config.camera.codec,
            "created_at": datetime.now().isoformat(),
        }
    
    def _save_manifest(self, manifest: Dict[str, Any]) -> str:
        """Save manifest to file."""
        manifests_path = Path(self.config.storage.manifests_path)
        manifests_path.mkdir(parents=True, exist_ok=True)
        
        filename = f"{manifest['session_id']}_{manifest['camera_id']}.json"
        manifest_path = manifests_path / filename
        
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
        
        return str(manifest_path)
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status."""
        return {
            "camera": {
                "detected": True,
                "model": self.camera_status.model,
                "resolution": self.camera_status.resolution,
                "fps": self.camera_status.fps,
                "codec": self.camera_status.codec,
                "bitrate_mbps": self.camera_status.bitrate_mbps,
                "simulation": True,
            },
            "recording": {
                "is_recording": self.recording_state.is_recording,
                "session_id": self.recording_state.session_id,
                "file_path": self.recording_state.file_path,
                "start_time_local": (
                    self.recording_state.start_time_local.isoformat()
                    if self.recording_state.start_time_local else None
                ),
                "duration_sec": self._get_duration(),
            }
        }
    
    def _get_duration(self) -> float:
        """Get current recording duration."""
        if not self.recording_state.is_recording or not self._recording_start:
            return self.recording_state.duration_sec
        return (datetime.now() - self._recording_start).total_seconds()
    
    def get_current_frame(self) -> Optional[Any]:
        """Get current frame (returns None for simulation)."""
        return None
    
    def get_preview_frame(self) -> Optional[bytes]:
        """Get preview frame (returns placeholder for simulation)."""
        # Could return a test pattern image here
        return None
    
    def capture_snapshot(self) -> Optional[bytes]:
        """Capture snapshot (returns None for simulation)."""
        return None
    
    def run_test_recording(self) -> Dict[str, Any]:
        """Run test recording."""
        logger.info("[SIMULATION] Running test recording...")
        
        # Start recording
        result = self.start_recording("TEST_SIMULATION")
        if not result.get("success"):
            return {"passed": False, "error": result.get("error")}
        
        # Wait short duration
        time.sleep(2)
        
        # Stop recording
        stop_result = self.stop_recording()
        
        # Cleanup
        file_path = Path(stop_result.get("file_path", ""))
        manifest_path = Path(stop_result.get("manifest_path", ""))
        
        if file_path.exists():
            file_path.unlink()
        if manifest_path.exists():
            manifest_path.unlink()
        
        return {
            "passed": True,
            "camera_detected": True,
            "recording_started": True,
            "recording_stopped": True,
            "simulation": True,
            "duration_sec": stop_result.get("duration_sec", 0),
        }
    
    def cleanup(self) -> None:
        """Clean up resources."""
        if self.recording_state.is_recording:
            self.stop_recording()
        logger.info("Simulation camera cleaned up")
    
    def supports_4k(self) -> bool:
        """Simulation supports any resolution."""
        return True
    
    def get_supported_resolutions(self) -> list:
        """All resolutions supported in simulation."""
        return ["3840x2160", "1920x1080", "1280x720", "640x480"]
    
    def get_supported_codecs(self) -> list:
        """All codecs ."""
        return ["h264", "h265"]
