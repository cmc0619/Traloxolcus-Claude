"""
Configuration for Processing Server.
"""

import os
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List


@dataclass
class ServerConfig:
    """Ingest server settings."""
    host: str = "0.0.0.0"
    port: int = 5100
    upload_max_size_gb: int = 50


@dataclass
class StorageConfig:
    """Local storage settings."""
    incoming_path: str = "/var/soccer-rig/incoming"  # Raw uploads land here
    processing_path: str = "/var/soccer-rig/processing"  # Working directory
    output_path: str = "/var/soccer-rig/output"  # Processed videos
    keep_raw_days: int = 7  # Days to keep raw files after processing


@dataclass
class StitcherConfig:
    """Video stitching settings."""
    enabled: bool = True
    use_gpu: bool = True  # Use NVENC for encoding
    output_resolution: tuple = (5760, 1080)  # Wide panorama
    output_fps: int = 30
    output_bitrate_mbps: int = 35
    codec: str = "h264_nvenc"  # h264_nvenc, hevc_nvenc, or libx264
    blend_width: int = 100  # Pixel overlap for blending
    calibration_file: Optional[str] = None  # Camera calibration data


@dataclass
class MLConfig:
    """ML pipeline settings."""
    enabled: bool = True
    use_gpu: bool = True
    device: str = "cuda:0"  # cuda:0 or cpu

    # Detection models
    player_model: str = "yolov8x.pt"  # YOLOv8 extra-large for accuracy
    ball_model: str = "yolov8n.pt"  # Smaller model for ball (faster)
    pose_model: str = "yolov8x-pose.pt"  # Pose estimation

    # Processing settings
    detection_fps: int = 10  # Analyze every N frames
    batch_size: int = 8  # Frames per batch (GPU memory dependent)
    confidence_threshold: float = 0.5

    # Event detection
    detect_goals: bool = True
    detect_shots: bool = True
    detect_saves: bool = True
    detect_passes: bool = True
    detect_fouls: bool = False  # Experimental


@dataclass
class PushConfig:
    """Settings for pushing to viewer server."""
    enabled: bool = True
    viewer_server_url: str = "https://your-viewer-server.com"
    api_key: str = ""  # Authentication key

    # Transfer method
    method: str = "api"  # "api", "rsync", or "s3"
    rsync_target: str = ""  # user@host:/path
    s3_bucket: str = ""

    # Options
    delete_after_push: bool = False
    retry_attempts: int = 3
    chunk_size_mb: int = 100  # For chunked uploads


@dataclass
class Config:
    """Main configuration."""
    server: ServerConfig = field(default_factory=ServerConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    stitcher: StitcherConfig = field(default_factory=StitcherConfig)
    ml: MLConfig = field(default_factory=MLConfig)
    push: PushConfig = field(default_factory=PushConfig)

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "Config":
        """Load configuration from YAML file."""
        if config_path and Path(config_path).exists():
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
        else:
            # Check default locations
            for path in [
                Path("config/processing.yaml"),
                Path("/etc/soccer-rig/processing.yaml"),
                Path.home() / ".config/soccer-rig/processing.yaml",
            ]:
                if path.exists():
                    with open(path) as f:
                        data = yaml.safe_load(f) or {}
                    break
            else:
                data = {}

        config = cls()

        if "server" in data:
            config.server = ServerConfig(**data["server"])
        if "storage" in data:
            config.storage = StorageConfig(**data["storage"])
        if "stitcher" in data:
            config.stitcher = StitcherConfig(**data["stitcher"])
        if "ml" in data:
            config.ml = MLConfig(**data["ml"])
        if "push" in data:
            config.push = PushConfig(**data["push"])

        # Environment variable overrides
        if os.getenv("VIEWER_SERVER_URL"):
            config.push.viewer_server_url = os.getenv("VIEWER_SERVER_URL")
        if os.getenv("VIEWER_API_KEY"):
            config.push.api_key = os.getenv("VIEWER_API_KEY")
        if os.getenv("USE_GPU"):
            use_gpu = os.getenv("USE_GPU").lower() == "true"
            config.stitcher.use_gpu = use_gpu
            config.ml.use_gpu = use_gpu

        return config
