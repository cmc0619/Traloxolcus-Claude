"""
Soccer Rig Processing Server.

GPU-accelerated video processing pipeline:
- Receives raw recordings from Pi nodes
- Stitches multi-camera footage into panorama
- Runs ML for event detection
- Pushes processed content to viewer server
"""

__version__ = "1.0.0"


def create_app():
    """
    WSGI application factory for the processing server.

    Used by gunicorn: gunicorn "src.processing_server:create_app()"

    This creates the Flask ingest server and starts background
    processing threads for stitching and ML.
    """
    import os
    import logging
    from .config import Config
    from .app import ProcessingPipeline

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)

    # Load configuration
    config_path = os.environ.get('CONFIG_PATH')
    config = Config.load(config_path)

    logger.info("=" * 60)
    logger.info("Soccer Rig Processing Server (WSGI)")
    logger.info("=" * 60)

    # Create processing pipeline
    pipeline = ProcessingPipeline(config)

    # Start background processing (stitcher, ML, push)
    pipeline.start()

    # Return the Flask app for WSGI
    return pipeline.ingest.app
