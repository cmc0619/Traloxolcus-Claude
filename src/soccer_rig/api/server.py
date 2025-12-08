"""
API Server for Soccer Rig.

Flask-based web server with REST API and static file serving.
"""

import logging
from flask import Flask, send_from_directory, Response
from flask_cors import CORS
from pathlib import Path

from soccer_rig.api.routes import create_api_blueprint

logger = logging.getLogger(__name__)


class APIServer:
    """
    Main API server class.

    Provides:
    - REST API endpoints
    - Static file serving for Web UI
    - MJPEG preview streaming
    """

    def __init__(self, app_context, host: str = "0.0.0.0", port: int = 8080):
        """
        Initialize API server.

        Args:
            app_context: SoccerRigApp instance
            host: Host to bind to
            port: Port to listen on
        """
        self.app_context = app_context
        self.host = host
        self.port = port
        self.flask_app = self._create_flask_app()

    def _create_flask_app(self) -> Flask:
        """Create and configure Flask application."""
        # Determine static folder path
        static_folder = self._find_static_folder()

        app = Flask(
            __name__,
            static_folder=static_folder,
            static_url_path=""
        )

        # Enable CORS for development
        CORS(app)

        # Register API blueprint
        api_blueprint = create_api_blueprint(self.app_context)
        app.register_blueprint(api_blueprint)

        # Register additional routes
        self._register_routes(app)

        return app

    def _find_static_folder(self) -> str:
        """Find the static files folder."""
        # Check various locations
        candidates = [
            Path(__file__).parent.parent.parent.parent / "web" / "static",
            Path("/opt/soccer-rig/web/static"),
            Path.home() / "soccer-rig" / "web" / "static",
        ]

        for path in candidates:
            if path.exists():
                return str(path)

        # Default to first candidate (will be created if needed)
        return str(candidates[0])

    def _register_routes(self, app: Flask) -> None:
        """Register additional routes."""

        @app.route("/")
        def index():
            """Serve the main UI."""
            return send_from_directory(
                app.static_folder,
                "index.html"
            )

        @app.route("/preview")
        def preview_stream():
            """MJPEG preview stream."""
            if not self.app_context.preview:
                return Response("Preview not available", status=503)

            return Response(
                self.app_context.preview.generate_mjpeg(),
                mimetype="multipart/x-mixed-replace; boundary=frame"
            )

        @app.route("/preview/snapshot")
        def preview_snapshot():
            """Single preview frame."""
            if not self.app_context.preview:
                return Response("Preview not available", status=503)

            frame, content_type = self.app_context.preview.get_single_frame_response()
            return Response(frame, mimetype=content_type)

        @app.route("/download/<path:filename>")
        def download_file(filename):
            """Download a recording file."""
            recordings_path = self.app_context.config.storage.recordings_path
            return send_from_directory(recordings_path, filename)

        @app.route("/manifest/<path:filename>")
        def get_manifest(filename):
            """Get a manifest file."""
            manifests_path = self.app_context.config.storage.manifests_path
            return send_from_directory(manifests_path, filename)

        @app.errorhandler(404)
        def not_found(e):
            """Handle 404 - serve index.html for SPA routes."""
            return send_from_directory(app.static_folder, "index.html")

        @app.errorhandler(500)
        def server_error(e):
            """Handle 500 errors."""
            logger.error(f"Server error: {e}")
            return {"error": "Internal server error"}, 500

    def run(self, debug: bool = False) -> None:
        """
        Run the Flask development server.

        Args:
            debug: Enable debug mode
        """
        logger.info(f"Starting API server on {self.host}:{self.port}")
        self.flask_app.run(
            host=self.host,
            port=self.port,
            debug=debug,
            threaded=True
        )

    def get_wsgi_app(self):
        """Get WSGI application for production deployment."""
        return self.flask_app
