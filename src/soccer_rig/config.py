"""
Configuration management for Soccer Rig.
"""

import os
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "/etc/soccer-rig/config.yaml"
USER_CONFIG_PATH = Path.home() / ".config" / "soccer-rig" / "config.yaml"


@dataclass
class CameraConfig:
    """Camera configuration settings."""
    id: str = "CAM_C"
    position: str = "center"  # left, center, right
    resolution_width: int = 3840
    resolution_height: int = 2160
    fps: int = 30
    codec: str = "h265"  # h265 or h264
    bitrate_mbps: int = 30
    container: str = "mp4"
    audio_enabled: bool = False
    test_duration_sec: int = 10


@dataclass
class NetworkConfig:
    """Network configuration settings."""
    mesh_ssid: str = "SOCCER_MESH"
    mesh_password: str = "soccer_rig_2024"
    ap_fallback_enabled: bool = True
    ap_fallback_timeout_sec: int = 30
    ap_ssid_prefix: str = "SOCCER_CAM_"
    ap_password: str = "soccercam123"
    web_port: int = 8080
    api_base_path: str = "/api/v1"


@dataclass
class StorageConfig:
    """Storage configuration settings."""
    recordings_path: str = "/mnt/nvme/recordings"
    manifests_path: str = "/mnt/nvme/manifests"
    min_free_space_gb: float = 10.0
    auto_delete_offloaded: bool = True
    delete_after_confirm: bool = False


@dataclass
class SyncConfig:
    """Time synchronization configuration."""
    is_master: bool = False
    master_ip: str = ""
    max_offset_ms: float = 5.0
    chrony_config_path: str = "/etc/chrony/chrony.conf"
    sync_check_interval_sec: int = 10


@dataclass
class UpdateConfig:
    """Software update configuration."""
    github_repo: str = ""
    check_on_boot: bool = False
    auto_apply: bool = False


@dataclass
class AudioConfig:
    """Audio feedback configuration."""
    enabled: bool = True
    volume: int = 80  # 0-100
    beep_on_record_start: bool = True
    beep_on_record_stop: bool = True
    beep_on_error: bool = True
    beep_on_sync: bool = True


@dataclass
class Config:
    """Main configuration class."""
    camera: CameraConfig = field(default_factory=CameraConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    update: UpdateConfig = field(default_factory=UpdateConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    production_mode: bool = True

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "Config":
        """Load configuration from file."""
        paths_to_try = []

        if config_path:
            paths_to_try.append(Path(config_path))

        paths_to_try.extend([
            Path(DEFAULT_CONFIG_PATH),
            USER_CONFIG_PATH,
            Path("config/config.yaml"),
        ])

        for path in paths_to_try:
            if path.exists():
                logger.info(f"Loading config from {path}")
                return cls._load_from_file(path)

        logger.warning("No config file found, using defaults")
        return cls()

    @classmethod
    def _load_from_file(cls, path: Path) -> "Config":
        """Load configuration from a YAML file."""
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}

        config = cls()

        if "camera" in data:
            config.camera = cls._load_dataclass(CameraConfig, data["camera"])
        if "network" in data:
            config.network = cls._load_dataclass(NetworkConfig, data["network"])
        if "storage" in data:
            config.storage = cls._load_dataclass(StorageConfig, data["storage"])
        if "sync" in data:
            config.sync = cls._load_dataclass(SyncConfig, data["sync"])
        if "update" in data:
            config.update = cls._load_dataclass(UpdateConfig, data["update"])
        if "audio" in data:
            config.audio = cls._load_dataclass(AudioConfig, data["audio"])
        if "production_mode" in data:
            config.production_mode = data["production_mode"]

        # Auto-set sync master based on camera position
        if config.camera.position == "center":
            config.sync.is_master = True

        return config

    @staticmethod
    def _load_dataclass(cls, data: Dict[str, Any]):
        """Load a dataclass from a dictionary."""
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered_data)

    def save(self, path: Optional[str] = None) -> None:
        """Save configuration to file."""
        save_path = Path(path) if path else USER_CONFIG_PATH
        save_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "camera": self._dataclass_to_dict(self.camera),
            "network": self._dataclass_to_dict(self.network),
            "storage": self._dataclass_to_dict(self.storage),
            "sync": self._dataclass_to_dict(self.sync),
            "update": self._dataclass_to_dict(self.update),
            "audio": self._dataclass_to_dict(self.audio),
            "production_mode": self.production_mode,
        }

        with open(save_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False)

        logger.info(f"Configuration saved to {save_path}")

    @staticmethod
    def _dataclass_to_dict(obj) -> Dict[str, Any]:
        """Convert a dataclass to a dictionary."""
        return {k: v for k, v in obj.__dict__.items()}

    def to_dict(self) -> Dict[str, Any]:
        """Convert entire config to dictionary."""
        return {
            "camera": self._dataclass_to_dict(self.camera),
            "network": self._dataclass_to_dict(self.network),
            "storage": self._dataclass_to_dict(self.storage),
            "sync": self._dataclass_to_dict(self.sync),
            "update": self._dataclass_to_dict(self.update),
            "audio": self._dataclass_to_dict(self.audio),
            "production_mode": self.production_mode,
        }

    def update_from_dict(self, data: Dict[str, Any]) -> None:
        """Update configuration from a dictionary."""
        if "camera" in data:
            for k, v in data["camera"].items():
                if hasattr(self.camera, k):
                    setattr(self.camera, k, v)
        if "network" in data:
            for k, v in data["network"].items():
                if hasattr(self.network, k):
                    setattr(self.network, k, v)
        if "storage" in data:
            for k, v in data["storage"].items():
                if hasattr(self.storage, k):
                    setattr(self.storage, k, v)
        if "sync" in data:
            for k, v in data["sync"].items():
                if hasattr(self.sync, k):
                    setattr(self.sync, k, v)
        if "update" in data:
            for k, v in data["update"].items():
                if hasattr(self.update, k):
                    setattr(self.update, k, v)
        if "audio" in data:
            for k, v in data["audio"].items():
                if hasattr(self.audio, k):
                    setattr(self.audio, k, v)
        if "production_mode" in data:
            self.production_mode = data["production_mode"]
