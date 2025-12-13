"""
WSGI application factory for Soccer Rig Viewer Server.

This module provides the create_app() factory function required by gunicorn.
"""

import os
import logging
from contextlib import contextmanager
from flask import Flask, request
from flask_cors import CORS
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

# Global debug flag - controls debug mode across the application
DEBUG = os.environ.get('DEBUG', 'false').lower() in ('true', '1', 'yes')

# Configure logging
log_level = logging.DEBUG if DEBUG else logging.INFO
logging.basicConfig(
    level=log_level,
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
    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key:
        if os.environ.get('FLASK_ENV') == 'production':
            raise RuntimeError("SECRET_KEY must be set in production")
        secret_key = 'dev-secret-change-me'
        logger.warning("Using insecure default SECRET_KEY - set SECRET_KEY environment variable")
    app.config['SECRET_KEY'] = secret_key
    app.config['DATABASE_URL'] = os.environ.get('DATABASE_URL', 'sqlite:///soccer.db')
    app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER', '/app/storage')
    app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max upload

    # TeamSnap OAuth
    app.config['TEAMSNAP_CLIENT_ID'] = os.environ.get('TEAMSNAP_CLIENT_ID', '')
    app.config['TEAMSNAP_CLIENT_SECRET'] = os.environ.get('TEAMSNAP_CLIENT_SECRET', '')

    # Enable CORS - configurable via environment variable
    cors_origins = os.environ.get('CORS_ORIGINS', '*')
    if cors_origins != '*':
        cors_origins = [o.strip() for o in cors_origins.split(',')]
    CORS(app, resources={r"/api/*": {"origins": cors_origins}})

    # Initialize database
    engine = get_engine(app.config['DATABASE_URL'])
    Base.metadata.create_all(engine)
    db = get_session(engine)

    # Store db session factory in app config for routes
    app.config['db'] = db

    # Register routes
    register_auth_routes(app, db)
    register_admin_routes(app)  # No db param needed
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

    # Index route - redirect to login or dashboard
    @app.route('/')
    def index():
        from flask import session, redirect, url_for
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return app.send_static_file('index.html')

    # Note: /dashboard route is registered in auth.py with login protection

    # Session context manager for clean resource handling
    @contextmanager
    def get_db_session():
        """Context manager for database sessions - ensures proper cleanup."""
        session = db()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # Health check - tests DB connectivity
    @app.route('/health')
    def health():
        try:
            with get_db_session() as session:
                session.execute(text('SELECT 1'))
                return {'status': 'ok', 'database': 'connected'}
        except SQLAlchemyError:
            logger.exception("Health check failed - database error")
            return {'status': 'error', 'database': 'disconnected'}, 503

    # Analytics/ML status endpoint
    @app.route('/analytics/status')
    def analytics_status():
        # ML pipeline runs on processing server, not viewer
        # Return a status indicating ML is available but runs externally
        processing_url = os.environ.get('PROCESSING_URL', '')
        return {
            'running': bool(processing_url),
            'models_loaded': bool(processing_url),
            'processing_server': processing_url or 'not configured'
        }

    # ==========================================================================
    # API v1 Endpoints (for dashboard frontend)
    # ==========================================================================
    from flask import session as flask_session
    from sqlalchemy.orm import joinedload, selectinload
    from src.models import Game, Recording, Team

    def _require_api_auth():
        """Check if user is authenticated for API access."""
        if not flask_session.get('user_id'):
            return {'error': 'Not authenticated'}, 401
        return None

    @app.route('/api/v1/stats')
    def api_stats():
        """Dashboard statistics."""
        auth_error = _require_api_auth()
        if auth_error:
            return auth_error

        try:
            with get_db_session() as session:
                total_games = session.query(Game).count()
                total_recordings = session.query(Recording).count()
                total_teams = session.query(Team).count()
                return {
                    'total_sessions': total_games,
                    'total_recordings': total_recordings,
                    'total_teams': total_teams,
                    'storage_used_gb': 0,  # TODO: Calculate from storage
                    'processing_queue': 0   # TODO: Query processing server
                }
        except SQLAlchemyError:
            logger.exception("Stats error - database query failed")
            return {'error': 'Database error'}, 500

    @app.route('/api/v1/sessions')
    def api_sessions():
        """List recording sessions (games)."""
        auth_error = _require_api_auth()
        if auth_error:
            return auth_error

        try:
            with get_db_session() as session:
                # Clamp limit to prevent heavy queries
                limit = min(request.args.get('limit', 50, type=int), 200)
                # Use joinedload for one-to-one (team), selectinload for one-to-many (recordings)
                games = session.query(Game).options(
                    joinedload(Game.team),
                    selectinload(Game.recordings)
                ).order_by(Game.created_at.desc()).limit(limit).all()
                return {
                    'sessions': [
                        {
                            'id': g.session_id or str(g.id),
                            'name': f"{g.team.name if g.team else 'Unknown'} vs {g.opponent or 'Unknown'}",
                            'created_at': g.created_at.isoformat() if g.created_at else None,
                            'game_date': g.game_date.isoformat() if g.game_date else None,
                            'complete': g.is_processed,
                            'stitched': bool(g.panorama_url),
                            'recording_count': len(g.recordings) if g.recordings else 0
                        }
                        for g in games
                    ],
                    'count': len(games)
                }
        except SQLAlchemyError:
            logger.exception("Sessions error - database query failed")
            return {'error': 'Database error'}, 500

    logger.info("Soccer Rig Viewer Server initialized")
    return app


# For development: python app.py
if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=DEBUG)
