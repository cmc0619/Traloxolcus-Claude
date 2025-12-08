"""
Main Soccer Rig application.

Orchestrates all components:
- Camera recorder
- REST API server
- Time sync
- Storage manager
- Audio feedback
- Network manager
- GitHub updater
"""

import signal
import logging
import sys
from typing import Optional

from soccer_rig.config import Config
from soccer_rig.camera import CameraRecorder, PreviewServer
from soccer_rig.camera.framing import FramingDetector, FramingAssistant
from soccer_rig.api import APIServer
from soccer_rig.storage import StorageManager
from soccer_rig.sync import SyncManager
from soccer_rig.audio import AudioFeedback
from soccer_rig.network import NetworkManager
from soccer_rig.updater import GitHubUpdater
from soccer_rig.coordinator import Coordinator
from soccer_rig.offload import OffloadClient

logger = logging.getLogger(__name__)


class SoccerRigApp:
    """
    Main application class.

    Manages lifecycle of all components and provides
    unified access to services.
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize Soccer Rig application.

        Args:
            config_path: Optional path to configuration file
        """
        # Load configuration
        self.config = Config.load(config_path)

        # Configure logging
        self._setup_logging()

        logger.info(f"Soccer Rig starting - Camera: {self.config.camera.id}")

        # Initialize components
        self.recorder: Optional[CameraRecorder] = None
        self.preview: Optional[PreviewServer] = None
        self.storage: Optional[StorageManager] = None
        self.sync: Optional[SyncManager] = None
        self.audio: Optional[AudioFeedback] = None
        self.network: Optional[NetworkManager] = None
        self.updater: Optional[GitHubUpdater] = None
        self.coordinator: Optional[Coordinator] = None
        self.framing: Optional[FramingDetector] = None
        self.framing_assistant: Optional[FramingAssistant] = None
        self.offload: Optional[OffloadClient] = None
        self.api_server: Optional[APIServer] = None

        self._running = False

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _setup_logging(self) -> None:
        """Configure logging based on mode."""
        level = logging.INFO

        if self.config.production_mode:
            # Production: minimal logging
            logging.basicConfig(
                level=level,
                format="%(levelname)s - %(message)s",
                handlers=[logging.StreamHandler(sys.stdout)]
            )
        else:
            # Development: full logging to file
            from pathlib import Path
            log_dir = Path("/var/log/soccer_rig")
            log_dir.mkdir(parents=True, exist_ok=True)

            logging.basicConfig(
                level=logging.DEBUG,
                format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                handlers=[
                    logging.StreamHandler(sys.stdout),
                    logging.FileHandler(log_dir / "soccer_rig.log"),
                ]
            )

    def _signal_handler(self, signum, frame) -> None:
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.shutdown()
        sys.exit(0)

    def _setup_peer_discovery(self) -> None:
        """Wire up network peer discovery to coordinator."""
        if not self.network or not self.coordinator:
            return

        # Check for discovered peers periodically
        import threading

        def check_peers():
            import time
            while self._running:
                try:
                    peers = self.network.get_peers()
                    for peer in peers:
                        camera_id = peer.get("camera_id")
                        ip = peer.get("ip")
                        port = peer.get("port", 8080)
                        position = peer.get("position", "")

                        if camera_id and ip and camera_id != self.config.camera.id:
                            self.coordinator.update_peer_from_discovery(
                                camera_id, ip, port, position
                            )
                except Exception as e:
                    logger.error(f"Peer discovery update error: {e}")

                time.sleep(5)

        self._peer_discovery_thread = threading.Thread(target=check_peers, daemon=True)
        self._peer_discovery_thread.start()

    def initialize(self) -> bool:
        """
        Initialize all components.

        Returns:
            True if initialization successful
        """
        try:
            logger.info("Initializing components...")

            # Initialize audio first for feedback
            self.audio = AudioFeedback(self.config)

            # Initialize storage
            self.storage = StorageManager(self.config)
            logger.info("Storage manager initialized")

            # Initialize sync manager
            self.sync = SyncManager(self.config)
            logger.info("Sync manager initialized")

            # Initialize network
            self.network = NetworkManager(self.config)
            logger.info("Network manager initialized")

            # Initialize camera
            self.recorder = CameraRecorder(self.config)
            logger.info("Camera recorder initialized")

            # Initialize preview server
            self.preview = PreviewServer(self.recorder)
            logger.info("Preview server initialized")

            # Initialize framing detection (for field positioning assistance)
            try:
                self.framing = FramingDetector(self.config)
                self.framing_assistant = FramingAssistant(
                    self.framing,
                    audio_feedback=self.audio
                )
                # Store assistant reference on detector for API access
                self.framing.assistant = self.framing_assistant
                logger.info("Framing detection initialized")
            except Exception as e:
                logger.warning(f"Framing detection unavailable: {e}")
                self.framing = None
                self.framing_assistant = None

            # Initialize updater
            self.updater = GitHubUpdater(self.config)
            logger.info("Updater initialized")

            # Initialize coordinator for multi-camera control
            self.coordinator = Coordinator(
                self.config,
                local_recorder=self.recorder,
                local_sync=self.sync,
                local_storage=self.storage
            )
            self.coordinator.start()
            logger.info("Coordinator initialized")

            # Wire up network discovery to coordinator
            self._setup_peer_discovery()

            # Initialize offload client for server uploads
            try:
                self.offload = OffloadClient(
                    self.config,
                    storage_manager=self.storage
                )
                logger.info("Offload client initialized")
            except Exception as e:
                logger.warning(f"Offload client unavailable: {e}")
                self.offload = None

            # Initialize API server
            self.api_server = APIServer(
                self,
                host="0.0.0.0",
                port=self.config.network.web_port
            )
            logger.info("API server initialized")

            # Play startup sound
            if self.audio:
                self.audio.play_startup_sound()

            logger.info("All components initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Initialization failed: {e}")
            if self.audio:
                self.audio.beep_error()
            return False

    def run(self) -> None:
        """
        Start the application.

        Blocks until shutdown is requested.
        """
        if not self.initialize():
            logger.error("Failed to initialize, exiting")
            sys.exit(1)

        self._running = True

        # Start preview server
        if self.preview:
            self.preview.start()

        # Start API server (blocking)
        logger.info(f"Starting web server on port {self.config.network.web_port}")
        try:
            self.api_server.run(debug=not self.config.production_mode)
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """Gracefully shutdown all components."""
        if not self._running:
            return

        self._running = False
        logger.info("Shutting down Soccer Rig...")

        # Play shutdown sound
        if self.audio:
            self.audio.play_shutdown_sound()

        # Stop recording if active
        if self.recorder and self.recorder.recording_state.is_recording:
            logger.info("Stopping active recording...")
            self.recorder.stop_recording()

        # Stop preview
        if self.preview:
            self.preview.stop()

        # Cleanup camera
        if self.recorder:
            self.recorder.cleanup()

        # Stop coordinator
        if self.coordinator:
            self.coordinator.stop()

        # Stop offload client
        if self.offload:
            self.offload.stop()

        # Cleanup network
        if self.network:
            self.network.cleanup()

        logger.info("Shutdown complete")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Soccer Rig Camera Node")
    parser.add_argument(
        "-c", "--config",
        help="Path to configuration file",
        default=None
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Run in development mode"
    )

    args = parser.parse_args()

    app = SoccerRigApp(config_path=args.config)

    if args.dev:
        app.config.production_mode = False

    app.run()


if __name__ == "__main__":
    main()
