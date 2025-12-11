"""
WSGI application factory for Soccer Rig Viewer Server.

This module provides the create_app() factory function required by gunicorn.
"""

import os
import logging
from flask import Flask
from flask_cors import CORS

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_app():
    """
    Create and configure the Flask application.

    This factory function is used by gunicorn:
        gunicorn "app:create_app()"
    """
    from src.models import Base, get_engine, get_session
    from src.auth import register_auth_routes
    from src.admin import register_admin_routes
    from src.services.heatmap import register_heatmap_routes
    from src.services.social_export import register_social_routes

    app = Flask(__name__,
                static_folder='web/static',
                template_folder='web/templates')

    # Configuration
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-me')
    app.config['DATABASE_URL'] = os.environ.get('DATABASE_URL', 'sqlite:///soccer.db')
    app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER', '/app/storage')
    app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max upload

    # TeamSnap OAuth
    app.config['TEAMSNAP_CLIENT_ID'] = os.environ.get('TEAMSNAP_CLIENT_ID', '')
    app.config['TEAMSNAP_CLIENT_SECRET'] = os.environ.get('TEAMSNAP_CLIENT_SECRET', '')

    # Enable CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Initialize database
    engine = get_engine(app.config['DATABASE_URL'])
    Base.metadata.create_all(engine)
    db = get_session(engine)

    # Store db session factory in app config for routes
    app.config['db'] = db

    # Register routes
    register_auth_routes(app, db)
    register_admin_routes(app, db)
    register_heatmap_routes(app, db)
    register_social_routes(app, db)

    # Register TeamSnap routes if configured
    if app.config['TEAMSNAP_CLIENT_ID']:
        try:
            from src.integrations.teamsnap import register_teamsnap_routes
            register_teamsnap_routes(app, db)
            logger.info("TeamSnap integration enabled")
        except ImportError:
            logger.warning("TeamSnap integration not available")

    # Index route - static landing page
    @app.route('/')
    def index():
        return app.send_static_file('index.html')

    # Note: /dashboard route is registered in auth.py with login protection

    # Health check
    @app.route('/health')
    def health():
        return {'status': 'ok'}

    logger.info("Soccer Rig Viewer Server initialized")
    return app


# For development: python app.py
if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=True)
