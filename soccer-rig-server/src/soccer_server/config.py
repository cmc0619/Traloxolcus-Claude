"""
Server configuration management.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import yaml


@dataclass
class StorageConfig:
    """Storage configuration."""
    base_path: str = "/var/lib/soccer-server/recordings"
    temp_path: str = "/var/lib/soccer-server/temp"
    clips_path: str = "/var/lib/soccer-server/clips"
    max_storage_gb: int = 1000  # 1TB default
    cleanup_after_days: int = 30


@dataclass
class ServerConfig:
    """Web server configuration."""
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    upload_max_size_gb: int = 50  # Max single upload size


@dataclass
class ProcessingConfig:
    """Video processing configuration."""
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    stitch_enabled: bool = True
    stitch_output_width: int = 7680  # 8K panorama
    stitch_output_height: int = 2160
    stitch_codec: str = "libx265"
    stitch_crf: int = 23


@dataclass
class CeleryConfig:
    """Task queue configuration."""
    broker_url: str = "redis://localhost:6379/0"
    result_backend: str = "redis://localhost:6379/0"


@dataclass
class DatabaseConfig:
    """Database configuration."""
    # Connection URL - supports PostgreSQL and MySQL
    # PostgreSQL: postgresql://user:pass@localhost:5432/soccer_rig
    # MySQL: mysql+pymysql://user:pass@localhost:3306/soccer_rig
    url: str = "postgresql://localhost:5432/soccer_rig"
    pool_size: int = 5
    max_overflow: int = 10


@dataclass
class AnalyticsConfig:
    """Video analytics configuration."""
    enabled: bool = True

    # Model paths
    player_detection_model: str = "yolov8n.pt"
    ball_detection_model: str = "ball_detector.pt"
    action_classifier_model: str = "action_classifier.pt"

    # Processing settings
    detection_fps: int = 5  # Sample rate for detection (frames per second)
    tracking_enabled: bool = True
    action_detection_enabled: bool = True

    # Confidence thresholds
    detection_confidence: float = 0.5
    action_confidence: float = 0.6

    # GPU settings
    use_gpu: bool = True
    gpu_device: int = 0


@dataclass
class Config:
    """Main server configuration."""
    storage: StorageConfig = field(default_factory=StorageConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)
    celery: CeleryConfig = field(default_factory=CeleryConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    analytics: AnalyticsConfig = field(default_factory=AnalyticsConfig)

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "Config":
        """Load configuration from file or environment."""
        config = cls()

        # Try config file
        if config_path and Path(config_path).exists():
            with open(config_path) as f:
                data = yaml.safe_load(f)
                config = cls._from_dict(data)

        # Environment overrides
        if os.getenv("STORAGE_PATH"):
            config.storage.base_path = os.getenv("STORAGE_PATH")
        if os.getenv("SERVER_PORT"):
            config.server.port = int(os.getenv("SERVER_PORT"))
        if os.getenv("REDIS_URL"):
            config.celery.broker_url = os.getenv("REDIS_URL")
            config.celery.result_backend = os.getenv("REDIS_URL")
        if os.getenv("DATABASE_URL"):
            config.database.url = os.getenv("DATABASE_URL")

        # Ensure directories exist
        Path(config.storage.base_path).mkdir(parents=True, exist_ok=True)
        Path(config.storage.temp_path).mkdir(parents=True, exist_ok=True)
        Path(config.storage.clips_path).mkdir(parents=True, exist_ok=True)

        return config

    @classmethod
    def _from_dict(cls, data: dict) -> "Config":
        """Create config from dictionary."""
        config = cls()

        if "storage" in data:
            for k, v in data["storage"].items():
                if hasattr(config.storage, k):
                    setattr(config.storage, k, v)

        if "server" in data:
            for k, v in data["server"].items():
                if hasattr(config.server, k):
                    setattr(config.server, k, v)

        if "processing" in data:
            for k, v in data["processing"].items():
                if hasattr(config.processing, k):
                    setattr(config.processing, k, v)

        if "celery" in data:
            for k, v in data["celery"].items():
                if hasattr(config.celery, k):
                    setattr(config.celery, k, v)

        if "database" in data:
            for k, v in data["database"].items():
                if hasattr(config.database, k):
                    setattr(config.database, k, v)

        if "analytics" in data:
            for k, v in data["analytics"].items():
                if hasattr(config.analytics, k):
                    setattr(config.analytics, k, v)

        return config
