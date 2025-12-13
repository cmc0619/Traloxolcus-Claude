"""
Abstract base class for camera recorders.

Implement this interface to support different camera modules:
- Pi Camera (V2, HQ, V3)
- USB cameras (UVC)
- IP cameras (RTSP)
- NDI cameras
- Virtual/test cameras
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class RecordingState:
    """Current recording state."""
    is_recording: bool = False
    session_id: str = ""
    file_path: str = ""
    start_time_local: Optional[datetime] = None
    start_time_master: Optional[datetime] = None
    offset_ms: float = 0.0
    duration_sec: float = 0.0
    dropped_frames: int = 0
    error: Optional[str] = None


@dataclass
class CameraStatus:
    """Camera hardware status."""
    detected: bool = False
    model: str = ""
    resolution: str = ""
    fps: int = 0
    codec: str = ""
    bitrate_mbps: int = 0
    temperature_c: float = 0.0
    error: Optional[str] = None


class BaseCameraRecorder(ABC):
    """
    Abstract base class for camera recorders.
    
    Implement this interface to add support for different camera types.
    All camera implementations must provide these methods.
    
    Example usage:
        class USBCameraRecorder(BaseCameraRecorder):
            def _init_camera(self) -> bool:
                # Initialize USB camera
                ...
    """
    
    def __init__(self, config):
        """
        Initialize the camera recorder.
        
        Args:
            config: Configuration object with camera settings
        """
        self.config = config
        self.recording_state = RecordingState()
        self.camera_status = CameraStatus()
    
    @abstractmethod
    def _init_camera(self) -> bool:
        """
        Initialize the camera hardware.
        
        Returns:
            True if initialization successful
        """
        pass
    
    @abstractmethod
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
        pass
    
    @abstractmethod
    def stop_recording(self) -> Dict[str, Any]:
        """
        Stop video recording and generate manifest.
        
        Returns:
            Dict with recording summary and manifest path
        """
        pass
    
    @abstractmethod
    def get_status(self) -> Dict[str, Any]:
        """
        Get current camera and recording status.
        
        Returns:
            Dict with camera and recording status
        """
        pass
    
    @abstractmethod
    def get_current_frame(self) -> Optional[Any]:
        """
        Get current camera frame as numpy array.
        
        Used for framing detection and live preview.
        
        Returns:
            numpy array (BGR format) or None if not available
        """
        pass
    
    @abstractmethod
    def get_preview_frame(self) -> Optional[bytes]:
        """
        Get current frame for live preview (JPEG bytes).
        
        Returns:
            JPEG image bytes or None
        """
        pass
    
    @abstractmethod
    def capture_snapshot(self) -> Optional[bytes]:
        """
        Capture a single frame as JPEG.
        
        Returns:
            JPEG image bytes or None
        """
        pass
    
    @abstractmethod
    def run_test_recording(self) -> Dict[str, Any]:
        """
        Run a short test recording to verify system.
        
        Returns:
            Dict with test results and pass/fail status
        """
        pass
    
    @abstractmethod
    def cleanup(self) -> None:
        """Clean up camera resources."""
        pass
    
    # Optional: Override these for custom behavior
    
    def supports_4k(self) -> bool:
        """Check if camera supports 4K resolution."""
        return False
    
    def supports_audio(self) -> bool:
        """Check if camera supports audio recording."""
        return False
    
    def get_supported_resolutions(self) -> list:
        """Get list of supported resolutions."""
        return []
    
    def get_supported_codecs(self) -> list:
        """Get list of supported codecs."""
        return ["h264"]


# =============================================================================
# Camera Registry - Auto-discovery of camera implementations
# =============================================================================

_camera_registry: Dict[str, type] = {}


def register_camera(camera_type: str):
    """
    Decorator to register a camera implementation.
    
    Usage:
        @register_camera("picamera2")
        class PiCameraRecorder(BaseCameraRecorder):
            ...
    """
    def decorator(cls):
        _camera_registry[camera_type] = cls
        logger.info(f"Registered camera type: {camera_type}")
        return cls
    return decorator


def get_available_cameras() -> list:
    """Get list of available camera types."""
    return list(_camera_registry.keys())


def create_camera_recorder(camera_type: str, config) -> Optional[BaseCameraRecorder]:
    """
    Create a camera recorder of the specified type.
    
    Args:
        camera_type: Type of camera (e.g., "picamera2", "usb", "rtsp")
        config: Configuration object
        
    Returns:
        Camera recorder instance or None if type not found
    """
    if camera_type not in _camera_registry:
        logger.error(f"Unknown camera type: {camera_type}. Available: {list(_camera_registry.keys())}")
        return None
    
    try:
        return _camera_registry[camera_type](config)
    except Exception as e:
        logger.error(f"Failed to create {camera_type} camera: {e}")
        return None


def auto_detect_camera(config) -> Optional[BaseCameraRecorder]:
    """
    Auto-detect and create the appropriate camera recorder.
    
    Tries cameras in order of preference:
    1. picamera2 (Pi Camera)
    2. usb (USB/UVC camera)
    3. simulation (virtual camera for testing)
    
    Returns:
        Camera recorder instance or None
    """
    # Priority order for auto-detection
    priority = ["picamera2", "usb", "rtsp", "simulation"]
    
    for camera_type in priority:
        if camera_type in _camera_registry:
            try:
                recorder = _camera_registry[camera_type](config)
                if recorder.camera_status.detected:
                    logger.info(f"Auto-detected camera: {camera_type}")
                    return recorder
            except Exception as e:
                logger.debug(f"Camera type {camera_type} not available: {e}")
    
    # Fall back to simulation mode
    if "simulation" in _camera_registry:
        logger.warning("No physical camera detected, using simulation mode")
        return _camera_registry["simulation"](config)
    
    return None
