"""
Main Soccer Rig Server application.

Central server for receiving recordings from Pi nodes,
managing storage, processing videos, and video analytics.
"""

import logging
import sys
from pathlib import Path
from typing import Optional

from flask import Flask, send_from_directory
from flask_cors import CORS

from soccer_server.config import Config
from soccer_server.storage import StorageManager
from soccer_server.stitcher import VideoStitcher
from soccer_server.api import create_api

logger = logging.getLogger(__name__)


class SoccerRigServer:
    """
    Main server application.

    Manages:
    - Recording storage and organization
    - API for Pi nodes and web dashboard
    - Video stitching pipeline
    - Video analytics (player tracking, event detection)
    - Natural language query interface
    - Clip generation for player highlights
    - Web dashboard
    """

    def __init__(self, config_path: Optional[str] = None):
        """Initialize the server."""
        self.config = Config.load(config_path)
        self._setup_logging()

        logger.info("Soccer Rig Server starting...")

        # Initialize components
        self.storage = StorageManager(self.config)
        logger.info("Storage manager initialized")

        self.stitcher = VideoStitcher(self.config, self.storage)
        self.stitcher.start()
        logger.info("Video stitcher initialized")

        # Initialize database (optional)
        self.db_manager = None
        if self.config.database.url:
            try:
                from soccer_server.database import DatabaseManager
                self.db_manager = DatabaseManager(self.config.database.url)
                self.db_manager.create_tables()
                logger.info("Database initialized")
            except Exception as e:
                logger.warning(f"Database not available: {e}")

        # Initialize analytics pipeline (optional)
        self.analytics = None
        if self.config.analytics.enabled and self.db_manager:
            try:
                from soccer_server.analytics import AnalysisPipeline
                self.analytics = AnalysisPipeline(self.config, self.db_manager)
                self.analytics.start()
                logger.info("Analytics pipeline initialized")
            except Exception as e:
                logger.warning(f"Analytics not available: {e}")

        # Initialize clip generator
        self.clip_generator = None
        try:
            from soccer_server.analytics import ClipGenerator
            self.clip_generator = ClipGenerator(self.config)
            logger.info("Clip generator initialized")
        except Exception as e:
            logger.warning(f"Clip generator not available: {e}")

        # Create Flask app
        self.app = self._create_app()
        logger.info("Flask app created")

    def _setup_logging(self) -> None:
        """Configure logging."""
        log_level = logging.DEBUG if self.config.server.debug else logging.INFO

        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.StreamHandler(sys.stdout),
            ]
        )

    def _create_app(self) -> Flask:
        """Create and configure Flask application."""
        app = Flask(
            __name__,
            static_folder=str(Path(__file__).parent.parent.parent / "web" / "static"),
            static_url_path="/static"
        )

        # Enable CORS for API
        CORS(app, resources={r"/api/*": {"origins": "*"}})

        # Configure upload limits
        app.config["MAX_CONTENT_LENGTH"] = self.config.server.upload_max_size_gb * 1024 * 1024 * 1024

        # Register API blueprint with all components
        api = create_api(
            storage=self.storage,
            stitcher=self.stitcher,
            db_manager=self.db_manager,
            analytics=self.analytics,
            clip_generator=self.clip_generator,
        )
        app.register_blueprint(api)

        # Serve web dashboard (admin)
        @app.route("/")
        def index():
            return send_from_directory(
                str(Path(__file__).parent.parent.parent / "web" / "static"),
                "index.html"
            )

        @app.route("/admin")
        def admin_dashboard():
            """Admin dashboard alias."""
            return send_from_directory(
                str(Path(__file__).parent.parent.parent / "web" / "static"),
                "index.html"
            )

        # Serve viewer portal (end users: parents, coaches, players)
        @app.route("/watch")
        def viewer_portal():
            """
            End-user viewer portal for watching games.

            Accessible to parents, coaches, players, scouts with team codes.
            """
            return send_from_directory(
                str(Path(__file__).parent.parent.parent / "web" / "static"),
                "watch.html"
            )

        @app.route("/<path:path>")
        def static_files(path):
            return send_from_directory(
                str(Path(__file__).parent.parent.parent / "web" / "static"),
                path
            )

        return app

    def run(self, host: Optional[str] = None, port: Optional[int] = None) -> None:
        """Run the server."""
        host = host or self.config.server.host
        port = port or self.config.server.port

        logger.info(f"Starting server on {host}:{port}")
        self.app.run(
            host=host,
            port=port,
            debug=self.config.server.debug,
            threaded=True,
        )

    def shutdown(self) -> None:
        """Shutdown the server."""
        logger.info("Shutting down...")

        if self.analytics:
            self.analytics.stop()

        self.stitcher.stop()


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Soccer Rig Server")
    parser.add_argument("-c", "--config", help="Path to config file")
    parser.add_argument("-p", "--port", type=int, help="Server port")
    parser.add_argument("--host", help="Server host")
    parser.add_argument("--debug", action="store_true", help="Debug mode")
    parser.add_argument("--init-db", action="store_true", help="Initialize database only")

    args = parser.parse_args()

    server = SoccerRigServer(config_path=args.config)

    if args.init_db:
        if server.db_manager:
            print("Database tables created successfully")
        else:
            print("Database not configured")
        return

    if args.debug:
        server.config.server.debug = True

    try:
        server.run(host=args.host, port=args.port)
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
