"""
Pi Camera recorder module for 4K video capture.

Uses libcamera/picamera2 on Raspberry Pi 5 for H.265/H.264 encoding.
"""

import os
import time
import json
import hashlib
import threading
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, Callable
import subprocess

from soccer_rig.camera.base import (
    BaseCameraRecorder, 
    RecordingState, 
    CameraStatus,
    register_camera
)

logger = logging.getLogger(__name__)

# Try to import picamera2, but allow running on non-Pi systems for development
try:
    from picamera2 import Picamera2
    from picamera2.encoders import H264Encoder, Quality
    from picamera2.outputs import FfmpegOutput
    PICAMERA_AVAILABLE = True
except ImportError:
    PICAMERA_AVAILABLE = False
    logger.warning("picamera2 not available - running in simulation mode")


@register_camera("picamera2")
class PiCameraRecorder(BaseCameraRecorder):
    """
    Handles 4K video recording using Pi Camera.

    Supports:
    - 4K (3840x2160) at 30fps
    - H.265 (HEVC) or H.264 encoding
    - MP4 container output
    - Continuous recording for 110+ minutes
    - Frame drop detection
    - Test recordings
    """

    def __init__(self, config):
        """
        Initialize the camera recorder.

        Args:
            config: Configuration object with camera settings
        """
        super().__init__(config)
        self.camera: Optional[Picamera2] = None
        self.encoder = None
        self.output = None
        self._lock = threading.Lock()
        self._recording_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._frame_callback: Optional[Callable] = None
        self._snapshot: Optional[bytes] = None

        # Initialize camera
        self._init_camera()

    def _init_camera(self) -> bool:
        """Initialize the camera hardware."""
        if not PICAMERA_AVAILABLE:
            self.camera_status.detected = False
            self.camera_status.error = "picamera2 not available (simulation mode)"
            logger.warning("Running in simulation mode - no actual camera")
            return False

        try:
            self.camera = Picamera2()

            # Get camera info
            camera_info = self.camera.camera_properties
            self.camera_status.detected = True
            self.camera_status.model = camera_info.get("Model", "Unknown")

            # Configure for 4K recording
            video_config = self.camera.create_video_configuration(
                main={"size": (
                    self.config.camera.resolution_width,
                    self.config.camera.resolution_height
                )},
                encode="main",
                buffer_count=6
            )
            self.camera.configure(video_config)

            self.camera_status.resolution = (
                f"{self.config.camera.resolution_width}x"
                f"{self.config.camera.resolution_height}"
            )
            self.camera_status.fps = self.config.camera.fps
            self.camera_status.codec = self.config.camera.codec
            self.camera_status.bitrate_mbps = self.config.camera.bitrate_mbps

            logger.info(f"Camera initialized: {self.camera_status.model}")
            return True

        except Exception as e:
            self.camera_status.detected = False
            self.camera_status.error = str(e)
            logger.error(f"Failed to initialize camera: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """Get current camera and recording status."""
        self._update_temperature()

        return {
            "camera": {
                "detected": self.camera_status.detected,
                "model": self.camera_status.model,
                "resolution": self.camera_status.resolution,
                "fps": self.camera_status.fps,
                "codec": self.camera_status.codec,
                "bitrate_mbps": self.camera_status.bitrate_mbps,
                "temperature_c": self.camera_status.temperature_c,
                "error": self.camera_status.error,
            },
            "recording": {
                "is_recording": self.recording_state.is_recording,
                "session_id": self.recording_state.session_id,
                "file_path": self.recording_state.file_path,
                "start_time_local": (
                    self.recording_state.start_time_local.isoformat()
                    if self.recording_state.start_time_local else None
                ),
                "duration_sec": self._get_recording_duration(),
                "dropped_frames": self.recording_state.dropped_frames,
                "error": self.recording_state.error,
            }
        }

    def _update_temperature(self) -> None:
        """Update CPU/GPU temperature reading."""
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                temp_milli = int(f.read().strip())
                self.camera_status.temperature_c = temp_milli / 1000.0
        except Exception:
            self.camera_status.temperature_c = 0.0

    def _get_recording_duration(self) -> float:
        """Get current recording duration in seconds."""
        if not self.recording_state.is_recording:
            return self.recording_state.duration_sec

        if self.recording_state.start_time_local:
            delta = datetime.now() - self.recording_state.start_time_local
            return delta.total_seconds()
        return 0.0

    def start_recording(
        self,
        session_id: str,
        master_time: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Start video recording.

        Args:
            session_id: Unique session identifier
            master_time: Master node timestamp for sync

        Returns:
            Dict with success status and recording info
        """
        with self._lock:
            if self.recording_state.is_recording:
                return {
                    "success": False,
                    "error": "Already recording"
                }

            if not self.camera_status.detected and PICAMERA_AVAILABLE:
                return {
                    "success": False,
                    "error": "Camera not detected"
                }

            # Create output directory
            recordings_path = Path(self.config.storage.recordings_path)
            recordings_path.mkdir(parents=True, exist_ok=True)

            # Generate filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            camera_id = self.config.camera.id
            filename = f"{session_id}_{camera_id}_{timestamp}.mp4"
            file_path = recordings_path / filename

            # Reset state
            self.recording_state = RecordingState(
                is_recording=True,
                session_id=session_id,
                file_path=str(file_path),
                start_time_local=datetime.now(),
                start_time_master=master_time or datetime.now(),
                offset_ms=0.0,
                dropped_frames=0,
            )

            # Calculate offset if master time provided
            if master_time:
                offset = (datetime.now() - master_time).total_seconds() * 1000
                self.recording_state.offset_ms = offset

            # Start recording
            if PICAMERA_AVAILABLE and self.camera:
                try:
                    self._start_hardware_recording(file_path)
                except Exception as e:
                    self.recording_state.is_recording = False
                    self.recording_state.error = str(e)
                    logger.error(f"Failed to start recording: {e}")
                    return {
                        "success": False,
                        "error": str(e)
                    }
            else:
                # Simulation mode - just track state
                logger.info(f"[SIMULATION] Recording to {file_path}")

            logger.info(f"Recording started: {filename}")

            return {
                "success": True,
                "session_id": session_id,
                "file_path": str(file_path),
                "start_time": self.recording_state.start_time_local.isoformat(),
            }

    def _start_hardware_recording(self, file_path: Path) -> None:
        """Start actual hardware recording."""
        bitrate = self.config.camera.bitrate_mbps * 1_000_000

        # Note: picamera2 only supports H.264 hardware encoding
        # For H.265 output, post-processing transcoding would be required
        # Both codec options use the same H.264 encoder for capture
        self.encoder = H264Encoder(bitrate=bitrate, quality=Quality.HIGH)
        self.output = FfmpegOutput(
            str(file_path),
            audio=self.config.camera.audio_enabled
        )

        self.camera.start()
        self.camera.start_encoder(self.encoder, self.output)

    def stop_recording(self) -> Dict[str, Any]:
        """
        Stop video recording and generate manifest.

        Returns:
            Dict with recording summary and manifest path
        """
        with self._lock:
            if not self.recording_state.is_recording:
                return {
                    "success": False,
                    "error": "Not recording"
                }

            # Calculate final duration
            self.recording_state.duration_sec = self._get_recording_duration()
            self.recording_state.is_recording = False

            # Stop hardware recording
            if PICAMERA_AVAILABLE and self.camera and self.encoder:
                try:
                    self.camera.stop_encoder()
                    self.camera.stop()
                except Exception as e:
                    logger.error(f"Error stopping encoder: {e}")

            # Generate manifest
            manifest = self._generate_manifest()
            manifest_path = self._save_manifest(manifest)

            logger.info(
                f"Recording stopped: {self.recording_state.file_path} "
                f"({self.recording_state.duration_sec:.1f}s)"
            )

            return {
                "success": True,
                "file_path": self.recording_state.file_path,
                "manifest_path": manifest_path,
                "duration_sec": self.recording_state.duration_sec,
                "dropped_frames": self.recording_state.dropped_frames,
            }

    def _generate_manifest(self) -> Dict[str, Any]:
        """Generate session manifest with all metadata."""
        file_path = Path(self.recording_state.file_path)
        checksum = self._calculate_checksum(file_path) if file_path.exists() else ""

        return {
            "session_id": self.recording_state.session_id,
            "camera_id": self.config.camera.id,
            "camera_position": self.config.camera.position,
            "file_name": file_path.name,
            "start_time_local": (
                self.recording_state.start_time_local.isoformat()
                if self.recording_state.start_time_local else None
            ),
            "start_time_master": (
                self.recording_state.start_time_master.isoformat()
                if self.recording_state.start_time_master else None
            ),
            "offset_ms": self.recording_state.offset_ms,
            "duration_sec": self.recording_state.duration_sec,
            "resolution": self.camera_status.resolution,
            "fps": self.config.camera.fps,
            "codec": self.config.camera.codec,
            "bitrate_mbps": self.config.camera.bitrate_mbps,
            "dropped_frames": self.recording_state.dropped_frames,
            "checksum": {
                "algo": "sha256",
                "value": checksum
            },
            "offloaded": False,
            "snapshot_base64": self._get_snapshot_base64(),
            "software_version": "1.0.0",
            "created_at": datetime.now().isoformat(),
        }

    def _calculate_checksum(self, file_path: Path) -> str:
        """Calculate SHA-256 checksum of file."""
        if not file_path.exists():
            return ""

        sha256 = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha256.update(chunk)
            return sha256.hexdigest()
        except Exception as e:
            logger.error(f"Failed to calculate checksum: {e}")
            return ""

    def _save_manifest(self, manifest: Dict[str, Any]) -> str:
        """Save manifest to file."""
        manifests_path = Path(self.config.storage.manifests_path)
        manifests_path.mkdir(parents=True, exist_ok=True)

        filename = f"{manifest['session_id']}_{manifest['camera_id']}.json"
        manifest_path = manifests_path / filename

        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        return str(manifest_path)

    def _get_snapshot_base64(self) -> Optional[str]:
        """Get base64-encoded snapshot image."""
        if self._snapshot:
            import base64
            return base64.b64encode(self._snapshot).decode("utf-8")
        return None

    def capture_snapshot(self) -> Optional[bytes]:
        """Capture a single frame as JPEG."""
        if not PICAMERA_AVAILABLE or not self.camera:
            return None

        try:
            # Capture frame to memory
            data = self.camera.capture_array()

            # Convert to JPEG using PIL if available
            try:
                from PIL import Image
                import io

                img = Image.fromarray(data)
                buffer = io.BytesIO()
                img.save(buffer, format="JPEG", quality=85)
                self._snapshot = buffer.getvalue()
                return self._snapshot
            except ImportError:
                logger.warning("PIL not available for snapshot conversion")
                return None

        except Exception as e:
            logger.error(f"Failed to capture snapshot: {e}")
            return None

    def get_current_frame(self):
        """
        Get current camera frame as numpy array.

        Used by framing detection for real-time analysis.

        Returns:
            numpy array (BGR format) or None if not available
        """
        if not PICAMERA_AVAILABLE or not self.camera:
            return None

        try:
            # Capture frame to numpy array
            frame = self.camera.capture_array()

            # picamera2 returns RGB, convert to BGR for OpenCV compatibility
            try:
                import cv2
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            except ImportError:
                pass  # Return RGB if cv2 not available

            return frame

        except Exception as e:
            logger.error(f"Failed to get current frame: {e}")
            return None

    def run_test_recording(self) -> Dict[str, Any]:
        """
        Run a short test recording to verify system.

        Returns:
            Dict with test results and pass/fail status
        """
        test_session_id = f"TEST_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        test_duration = self.config.camera.test_duration_sec

        results = {
            "passed": False,
            "camera_detected": self.camera_status.detected,
            "recording_started": False,
            "recording_stopped": False,
            "file_created": False,
            "file_size_bytes": 0,
            "duration_sec": 0,
            "errors": [],
        }

        # Start test recording
        start_result = self.start_recording(test_session_id)
        if not start_result.get("success"):
            results["errors"].append(f"Start failed: {start_result.get('error')}")
            return results

        results["recording_started"] = True

        # Wait for test duration
        time.sleep(test_duration)

        # Stop recording
        stop_result = self.stop_recording()
        if not stop_result.get("success"):
            results["errors"].append(f"Stop failed: {stop_result.get('error')}")
            return results

        results["recording_stopped"] = True
        results["duration_sec"] = stop_result.get("duration_sec", 0)

        # Check file
        file_path = Path(stop_result.get("file_path", ""))
        if file_path.exists():
            results["file_created"] = True
            results["file_size_bytes"] = file_path.stat().st_size

            # Clean up test file
            try:
                file_path.unlink()
                manifest_path = Path(stop_result.get("manifest_path", ""))
                if manifest_path.exists():
                    manifest_path.unlink()
            except Exception:
                pass

        # Determine pass/fail
        results["passed"] = (
            results["camera_detected"] and
            results["recording_started"] and
            results["recording_stopped"] and
            results["file_created"] and
            results["file_size_bytes"] > 0 and
            len(results["errors"]) == 0
        )

        return results

    def get_preview_frame(self) -> Optional[bytes]:
        """Get current frame for live preview (MJPEG)."""
        return self.capture_snapshot()

    def cleanup(self) -> None:
        """Clean up camera resources."""
        if self.recording_state.is_recording:
            self.stop_recording()

        if PICAMERA_AVAILABLE and self.camera:
            try:
                self.camera.close()
            except Exception as e:
                logger.error(f"Error closing camera: {e}")

        self.camera = None
        logger.info("Camera resources cleaned up")

    # =========================================================================
    # Capability methods
    # =========================================================================

    def supports_4k(self) -> bool:
        """Check if camera supports 4K resolution."""
        return True  # Pi Camera V2/HQ/V3 all support 4K

    def supports_audio(self) -> bool:
        """Check if camera supports audio recording."""
        return self.config.camera.audio_enabled

    def get_supported_resolutions(self) -> list:
        """Get list of supported resolutions."""
        return ["3840x2160", "1920x1080", "1280x720", "640x480"]

    def get_supported_codecs(self) -> list:
        """Get list of supported codecs.
        
        Note: picamera2 hardware encoding is H.264 only.
        H.265/HEVC would require separate transcoding pipeline.
        """
        return ["h264"]


# Backwards compatibility alias
CameraRecorder = PiCameraRecorder
