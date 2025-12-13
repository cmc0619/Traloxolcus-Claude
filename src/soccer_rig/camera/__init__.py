"""
Camera module for Soccer Rig.

Supports pluggable camera implementations:
- PiCameraRecorder: Raspberry Pi Camera (default)
- Create custom implementations by extending BaseCameraRecorder

Usage:
    # Use default camera (auto-detected or picamera2)
    from soccer_rig.camera import CameraRecorder
    recorder = CameraRecorder(config)
    
    # Or use the factory for auto-detection
    from soccer_rig.camera import auto_detect_camera
    recorder = auto_detect_camera(config)
    
    # Or create a specific type
    from soccer_rig.camera import create_camera_recorder
    recorder = create_camera_recorder("usb", config)
"""

# Base class and registry for custom implementations
from soccer_rig.camera.base import (
    BaseCameraRecorder,
    RecordingState,
    CameraStatus,
    register_camera,
    get_available_cameras,
    create_camera_recorder,
    auto_detect_camera,
)

# Default implementation (Pi Camera)
from soccer_rig.camera.recorder import (
    PiCameraRecorder,
    CameraRecorder,  # Backwards-compatible alias
)

# Simulation camera (auto-registers on import)
from soccer_rig.camera.simulation import SimulationCameraRecorder

# Preview server
from soccer_rig.camera.preview import PreviewServer

__all__ = [
    # Base class for custom implementations
    "BaseCameraRecorder",
    "RecordingState",
    "CameraStatus",
    "register_camera",
    
    # Factory functions
    "get_available_cameras",
    "create_camera_recorder",
    "auto_detect_camera",
    
    # Default implementations
    "PiCameraRecorder",
    "SimulationCameraRecorder",
    "CameraRecorder",  # Backwards-compatible alias
    "PreviewServer",
]
