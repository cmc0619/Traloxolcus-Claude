"""
Admin Authentication and Configuration

Features:
- Auto-generate admin password on first start
- Print password to logs on every Docker start
- Admin login required for config pages
- Expose all configuration items in web UI
"""

import os
import secrets
import logging
from functools import wraps
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from flask import Flask, request, session, jsonify, redirect, url_for, render_template_string

logger = logging.getLogger(__name__)

# =============================================================================
# Password Management
# =============================================================================

PASSWORD_FILE = os.getenv('ADMIN_PASSWORD_FILE', '/app/data/.admin_password')
ADMIN_USERNAME = 'admin'


def get_or_create_admin_password() -> str:
    """
    Get existing admin password or generate new one.
    Password is stored in a file and printed to logs on startup.
    """
    password_path = Path(PASSWORD_FILE)

    # Create directory if needed
    password_path.parent.mkdir(parents=True, exist_ok=True)

    if password_path.exists():
        password = password_path.read_text().strip()
        if password:
            return password

    # Generate new password (8 chars - we're not Fort Knox)
    password = secrets.token_urlsafe(6)
    password_path.write_text(password)
    password_path.chmod(0o600)  # Only owner can read

    logger.info("=" * 60)
    logger.info("NEW ADMIN PASSWORD GENERATED")
    logger.info("=" * 60)

    return password


def print_admin_credentials():
    """Print admin credentials to logs (called on every startup)."""
    password = get_or_create_admin_password()

    print("\n" + "=" * 60)
    print("SOCCER RIG ADMIN CREDENTIALS")
    print("=" * 60)
    print(f"  Username: {ADMIN_USERNAME}")
    print(f"  Password: {password}")
    print("=" * 60)
    print("  Use these credentials to access /admin")
    print("=" * 60 + "\n")

    logger.info("=" * 60)
    logger.info("ADMIN CREDENTIALS")
    logger.info(f"  Username: {ADMIN_USERNAME}")
    logger.info(f"  Password: {password}")
    logger.info("=" * 60)


def verify_admin_password(password: str) -> bool:
    """Verify admin password."""
    correct_password = get_or_create_admin_password()
    return secrets.compare_digest(password, correct_password)


def reset_admin_password() -> str:
    """Reset admin password to a new random value."""
    password_path = Path(PASSWORD_FILE)
    if password_path.exists():
        password_path.unlink()
    new_password = get_or_create_admin_password()
    print_admin_credentials()
    return new_password


# =============================================================================
# Authentication Decorator
# =============================================================================

def admin_required(f):
    """Decorator to require admin authentication."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            if request.is_json:
                return jsonify({'error': 'Admin authentication required'}), 401
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function


# =============================================================================
# Configuration Manager
# =============================================================================

class ConfigManager:
    """
    Manages runtime configuration with defaults from environment.
    """

    # Default configuration with descriptions
    CONFIG_SCHEMA = {
        # Email
        'SMTP_HOST': {
            'type': 'string',
            'default': 'smtp.gmail.com',
            'description': 'SMTP server hostname',
            'category': 'Email'
        },
        'SMTP_PORT': {
            'type': 'int',
            'default': 587,
            'description': 'SMTP server port',
            'category': 'Email'
        },
        'SMTP_USER': {
            'type': 'string',
            'default': '',
            'description': 'SMTP username',
            'category': 'Email'
        },
        'SMTP_PASS': {
            'type': 'password',
            'default': '',
            'description': 'SMTP password',
            'category': 'Email'
        },
        'EMAIL_FROM': {
            'type': 'string',
            'default': 'noreply@soccer-rig.local',
            'description': 'From email address',
            'category': 'Email'
        },

        # TeamSnap
        'TEAMSNAP_CLIENT_ID': {
            'type': 'string',
            'default': '',
            'description': 'TeamSnap OAuth Client ID',
            'category': 'TeamSnap'
        },
        'TEAMSNAP_CLIENT_SECRET': {
            'type': 'password',
            'default': '',
            'description': 'TeamSnap OAuth Client Secret',
            'category': 'TeamSnap'
        },
        'TEAMSNAP_REDIRECT_URI': {
            'type': 'string',
            'default': '',
            'description': 'OAuth callback URL',
            'category': 'TeamSnap'
        },

        # Processing
        'BENCH_URL': {
            'type': 'string',
            'default': 'http://localhost:5100',
            'description': 'Bench (processing server) URL',
            'category': 'Processing'
        },
        'AUTO_PROCESS': {
            'type': 'bool',
            'default': True,
            'description': 'Auto-process uploads when complete',
            'category': 'Processing'
        },

        # Storage
        'VIDEO_STORAGE_PATH': {
            'type': 'string',
            'default': '/app/storage',
            'description': 'Path to video storage',
            'category': 'Storage'
        },
        'MAX_UPLOAD_SIZE_GB': {
            'type': 'int',
            'default': 50,
            'description': 'Max upload size in GB',
            'category': 'Storage'
        },

        # SSL
        'SSL_MODE': {
            'type': 'select',
            'options': ['self-signed', 'letsencrypt'],
            'default': 'self-signed',
            'description': 'SSL certificate mode',
            'category': 'SSL'
        },
        'DOMAIN': {
            'type': 'string',
            'default': 'localhost',
            'description': 'Domain name for SSL',
            'category': 'SSL'
        },
        'ADMIN_EMAIL': {
            'type': 'string',
            'default': '',
            'description': 'Admin email for Let\'s Encrypt',
            'category': 'SSL'
        },

        # Features
        'ENABLE_NOTIFICATIONS': {
            'type': 'bool',
            'default': True,
            'description': 'Enable email notifications',
            'category': 'Features'
        },
        'ENABLE_HIGHLIGHTS': {
            'type': 'bool',
            'default': True,
            'description': 'Enable auto-generated highlights',
            'category': 'Features'
        },
        'ENABLE_TEAMSNAP': {
            'type': 'bool',
            'default': True,
            'description': 'Enable TeamSnap integration',
            'category': 'Features'
        }
    }

    def __init__(self, config_file: str = '/app/data/config.json'):
        self.config_file = Path(config_file)
        self._config: Dict[str, Any] = {}
        self._load()

    def _load(self):
        """Load config from file, falling back to env vars and defaults."""
        import json

        # Start with defaults
        for key, schema in self.CONFIG_SCHEMA.items():
            self._config[key] = os.getenv(key, schema['default'])

        # Load from file if exists
        if self.config_file.exists():
            try:
                with open(self.config_file) as f:
                    saved = json.load(f)
                    self._config.update(saved)
            except (json.JSONDecodeError, OSError, ValueError):
                logger.exception("Failed to load config file")

    def _save(self):
        """Save config to file."""
        import json

        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, 'w') as f:
            # Don't save passwords to file, keep in env
            safe_config = {
                k: v for k, v in self._config.items()
                if self.CONFIG_SCHEMA.get(k, {}).get('type') != 'password'
            }
            json.dump(safe_config, f, indent=2)

    def get(self, key: str) -> Any:
        """Get config value."""
        return self._config.get(key)

    def set(self, key: str, value: Any) -> bool:
        """Set config value."""
        if key not in self.CONFIG_SCHEMA:
            return False

        schema = self.CONFIG_SCHEMA[key]

        # Type conversion
        if schema['type'] == 'int':
            value = int(value)
        elif schema['type'] == 'bool':
            value = value in (True, 'true', 'True', '1', 1)

        self._config[key] = value
        self._save()

        # Also update environment for runtime
        os.environ[key] = str(value)
        return True

    def get_all(self) -> Dict[str, Dict]:
        """Get all config values grouped by category."""
        result = {}
        for key, schema in self.CONFIG_SCHEMA.items():
            category = schema['category']
            if category not in result:
                result[category] = {}

            value = self._config.get(key, schema['default'])

            # Mask passwords
            if schema['type'] == 'password' and value:
                display_value = '••••••••'
            else:
                display_value = value

            result[category][key] = {
                'value': display_value,
                'raw_value': value if schema['type'] != 'password' else None,
                'type': schema['type'],
                'description': schema['description'],
                'options': schema.get('options'),
                'default': schema['default']
            }

        return result


# Global config manager instance
config_manager = ConfigManager()


# =============================================================================
# Flask Routes
# =============================================================================

def register_admin_routes(app: Flask):
    """Register admin routes."""

    # Print credentials on startup
    print_admin_credentials()

    @app.route('/admin/login', methods=['GET', 'POST'])
    def admin_login():
        """Admin login page."""
        if request.method == 'POST':
            username = request.form.get('username', '')
            password = request.form.get('password', '')

            if username == ADMIN_USERNAME and verify_admin_password(password):
                session['is_admin'] = True
                session['admin_login_time'] = datetime.utcnow().isoformat()
                return redirect(url_for('admin_dashboard'))
            else:
                return render_template_string(ADMIN_LOGIN_HTML, error='Invalid credentials')

        return render_template_string(ADMIN_LOGIN_HTML, error=None)

    @app.route('/admin/logout')
    def admin_logout():
        """Admin logout."""
        session.pop('is_admin', None)
        session.pop('admin_login_time', None)
        return redirect(url_for('admin_login'))

    @app.route('/admin')
    @admin_required
    def admin_dashboard():
        """Admin dashboard."""
        config = config_manager.get_all()
        return render_template_string(ADMIN_DASHBOARD_HTML, config=config)

    @app.route('/admin/config', methods=['GET', 'POST'])
    @admin_required
    def admin_config():
        """Configuration page."""
        if request.method == 'POST':
            # Handle boolean checkboxes specially - unchecked boxes don't appear in form
            for key, schema in ConfigManager.CONFIG_SCHEMA.items():
                if schema['type'] == 'bool':
                    # Checkbox present = True, absent = False
                    config_manager.set(key, key in request.form)
                elif key in request.form:
                    config_manager.set(key, request.form[key])
            return redirect(url_for('admin_config'))

        config = config_manager.get_all()
        return render_template_string(ADMIN_CONFIG_HTML, config=config)

    @app.route('/api/admin/config', methods=['GET'])
    @admin_required
    def api_get_config():
        """Get config as JSON."""
        return jsonify(config_manager.get_all())

    @app.route('/api/admin/config', methods=['POST'])
    @admin_required
    def api_set_config():
        """Update config values."""
        data = request.get_json()
        updated = []
        for key, value in data.items():
            if config_manager.set(key, value):
                updated.append(key)
        return jsonify({'updated': updated})

    @app.route('/api/admin/password/reset', methods=['POST'])
    @admin_required
    def api_reset_password():
        """Reset admin password."""
        new_password = reset_admin_password()
        return jsonify({'message': 'Password reset. Check logs for new password.'})

    @app.route('/api/admin/health')
    @admin_required
    def api_admin_health():
        """System health check."""
        import psutil

        return jsonify({
            'cpu_percent': psutil.cpu_percent(),
            'memory_percent': psutil.virtual_memory().percent,
            'disk_percent': psutil.disk_usage('/').percent,
            'uptime': str(datetime.now() - datetime.fromtimestamp(psutil.boot_time()))
        })

    # =========================================================================
    # User Management
    # =========================================================================

    @app.route('/admin/users')
    @admin_required
    def admin_users():
        """User management page."""
        from .models import User
        from .database import get_db_session
        
        with get_db_session() as db:
            users = db.query(User).order_by(User.created_at.desc()).all()
            user_list = [{
                'id': u.id,
                'email': u.email,
                'first_name': u.first_name,
                'last_name': u.last_name,
                'role': u.role.value if u.role else 'user',
                'teamsnap_connected': bool(u.teamsnap_token),
                'created_at': u.created_at.isoformat() if u.created_at else None
            } for u in users]
        
        return render_template_string(ADMIN_USERS_HTML, users=user_list)

    @app.route('/api/admin/users', methods=['GET'])
    @admin_required
    def api_list_users():
        """Get all users as JSON."""
        from .models import User
        from .database import get_db_session
        
        with get_db_session() as db:
            users = db.query(User).order_by(User.created_at.desc()).all()
            return jsonify({
                'users': [{
                    'id': u.id,
                    'email': u.email,
                    'first_name': u.first_name,
                    'last_name': u.last_name,
                    'role': u.role.value if u.role else 'user',
                    'phone': u.phone,
                    'teamsnap_connected': bool(u.teamsnap_token),
                    'created_at': u.created_at.isoformat() if u.created_at else None
                } for u in users]
            })

    @app.route('/api/admin/users/<int:user_id>', methods=['GET'])
    @admin_required
    def api_get_user(user_id):
        """Get single user."""
        from .models import User
        from .database import get_db_session
        
        with get_db_session() as db:
            user = db.query(User).get(user_id)
            if not user:
                return jsonify({'error': 'User not found'}), 404
            return jsonify({
                'id': user.id,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'role': user.role.value if user.role else 'user',
                'phone': user.phone,
                'teamsnap_connected': bool(user.teamsnap_token)
            })

    @app.route('/api/admin/users/<int:user_id>', methods=['PUT'])
    @admin_required
    def api_update_user(user_id):
        """Update user."""
        from .models import User, UserRole
        from .database import get_db_session
        
        data = request.get_json()
        with get_db_session() as db:
            user = db.query(User).get(user_id)
            if not user:
                return jsonify({'error': 'User not found'}), 404
            
            if 'first_name' in data:
                user.first_name = data['first_name']
            if 'last_name' in data:
                user.last_name = data['last_name']
            if 'email' in data:
                user.email = data['email']
            if 'phone' in data:
                user.phone = data['phone']
            if 'role' in data:
                try:
                    user.role = UserRole(data['role'])
                except ValueError:
                    pass
            
            db.commit()
            return jsonify({'success': True})

    @app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
    @admin_required
    def api_delete_user(user_id):
        """Delete user."""
        from .models import User
        from .database import get_db_session
        
        with get_db_session() as db:
            user = db.query(User).get(user_id)
            if not user:
                return jsonify({'error': 'User not found'}), 404
            
            db.delete(user)
            db.commit()
            return jsonify({'success': True})

    @app.route('/api/admin/users/<int:user_id>/reset-password', methods=['POST'])
    @admin_required
    def api_reset_user_password(user_id):
        """Reset a user's password."""
        import secrets
        from werkzeug.security import generate_password_hash
        from .models import User
        from .database import get_db_session
        
        new_password = secrets.token_urlsafe(12)
        
        with get_db_session() as db:
            user = db.query(User).get(user_id)
            if not user:
                return jsonify({'error': 'User not found'}), 404
            
            user.password_hash = generate_password_hash(new_password)
            db.commit()
            
            return jsonify({
                'success': True,
                'new_password': new_password,
                'message': f'New password for {user.email}: {new_password}'
            })


# =============================================================================
# HTML Templates
# =============================================================================

ADMIN_LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Login - Soccer Rig</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0f172a; color: #f1f5f9; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
        .login-box { background: #1e293b; padding: 2rem; border-radius: 1rem; width: 100%; max-width: 400px; box-shadow: 0 10px 40px rgba(0,0,0,0.3); }
        h1 { text-align: center; margin-bottom: 2rem; font-size: 1.5rem; }
        .form-group { margin-bottom: 1.5rem; }
        label { display: block; margin-bottom: 0.5rem; font-size: 0.875rem; color: #94a3b8; }
        input { width: 100%; padding: 0.75rem 1rem; border: 2px solid #334155; border-radius: 0.5rem; background: #0f172a; color: #f1f5f9; font-size: 1rem; }
        input:focus { outline: none; border-color: #6366f1; }
        button { width: 100%; padding: 0.875rem; background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; border: none; border-radius: 0.5rem; font-size: 1rem; font-weight: 600; cursor: pointer; }
        button:hover { opacity: 0.9; }
        .error { background: #ef4444; padding: 0.75rem; border-radius: 0.5rem; margin-bottom: 1rem; text-align: center; }
    </style>
</head>
<body>
    <div class="login-box">
        <h1>⚽ Admin Login</h1>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        <form method="POST">
            <div class="form-group">
                <label>Username</label>
                <input type="text" name="username" required autofocus>
            </div>
            <div class="form-group">
                <label>Password</label>
                <input type="password" name="password" required>
            </div>
            <button type="submit">Login</button>
        </form>
    </div>
</body>
</html>
"""

ADMIN_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Dashboard - Soccer Rig</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0f172a; color: #f1f5f9; min-height: 100vh; }
        .header { background: #1e293b; padding: 1rem 2rem; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; }
        .header h1 { font-size: 1.25rem; }
        .header a { color: #94a3b8; text-decoration: none; }
        .header a:hover { color: #f1f5f9; }
        .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
        .nav { display: flex; gap: 1rem; margin-bottom: 2rem; }
        .nav a { padding: 0.75rem 1.5rem; background: #1e293b; border-radius: 0.5rem; color: #f1f5f9; text-decoration: none; }
        .nav a:hover, .nav a.active { background: #6366f1; }
        .card { background: #1e293b; border-radius: 1rem; padding: 1.5rem; margin-bottom: 1.5rem; }
        .card h2 { font-size: 1.125rem; margin-bottom: 1rem; color: #6366f1; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; }
        .stat { background: #0f172a; padding: 1rem; border-radius: 0.5rem; text-align: center; }
        .stat-value { font-size: 2rem; font-weight: 700; color: #6366f1; }
        .stat-label { color: #94a3b8; font-size: 0.875rem; }
    </style>
</head>
<body>
    <div class="header">
        <h1>⚽ Soccer Rig Admin</h1>
        <a href="/admin/logout">Logout</a>
    </div>
    <div class="container">
        <div class="nav">
            <a href="/admin" class="active">Dashboard</a>
            <a href="/admin/config">Configuration</a>
            <a href="/admin/users">Users</a>
        </div>

        <div class="card">
            <h2>Quick Status</h2>
            <div class="stats" id="stats">
                <div class="stat"><div class="stat-value" id="cpu">--</div><div class="stat-label">CPU</div></div>
                <div class="stat"><div class="stat-value" id="mem">--</div><div class="stat-label">Memory</div></div>
                <div class="stat"><div class="stat-value" id="disk">--</div><div class="stat-label">Disk</div></div>
            </div>
        </div>

        <div class="card">
            <h2>Configuration Summary</h2>
            {% for category, items in config.items() %}
            <h3 style="color: #94a3b8; margin-top: 1rem;">{{ category }}</h3>
            <ul style="list-style: none; margin-top: 0.5rem;">
                {% for key, item in items.items() %}
                <li style="padding: 0.25rem 0; border-bottom: 1px solid #334155;">
                    <span style="color: #94a3b8;">{{ key }}:</span>
                    <span>{{ item.value or '(not set)' }}</span>
                </li>
                {% endfor %}
            </ul>
            {% endfor %}
        </div>
    </div>

    <script>
        async function loadHealth() {
            try {
                const res = await fetch('/api/admin/health');
                const data = await res.json();
                document.getElementById('cpu').textContent = data.cpu_percent + '%';
                document.getElementById('mem').textContent = data.memory_percent + '%';
                document.getElementById('disk').textContent = data.disk_percent + '%';
            } catch (e) {
                console.error('Failed to load health', e);
            }
        }
        loadHealth();
        setInterval(loadHealth, 5000);
    </script>
</body>
</html>
"""

ADMIN_CONFIG_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Configuration - Soccer Rig Admin</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0f172a; color: #f1f5f9; min-height: 100vh; }
        .header { background: #1e293b; padding: 1rem 2rem; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; }
        .header h1 { font-size: 1.25rem; }
        .header a { color: #94a3b8; text-decoration: none; }
        .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
        .nav { display: flex; gap: 1rem; margin-bottom: 2rem; }
        .nav a { padding: 0.75rem 1.5rem; background: #1e293b; border-radius: 0.5rem; color: #f1f5f9; text-decoration: none; }
        .nav a:hover, .nav a.active { background: #6366f1; }
        .card { background: #1e293b; border-radius: 1rem; padding: 1.5rem; margin-bottom: 1.5rem; }
        .card h2 { font-size: 1.125rem; margin-bottom: 1rem; color: #6366f1; }
        .form-group { margin-bottom: 1rem; }
        label { display: block; margin-bottom: 0.25rem; font-size: 0.875rem; color: #94a3b8; }
        .description { font-size: 0.75rem; color: #64748b; margin-bottom: 0.5rem; }
        input, select { width: 100%; padding: 0.625rem 0.75rem; border: 2px solid #334155; border-radius: 0.5rem; background: #0f172a; color: #f1f5f9; font-size: 0.9375rem; }
        input:focus, select:focus { outline: none; border-color: #6366f1; }
        button { padding: 0.875rem 2rem; background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; border: none; border-radius: 0.5rem; font-size: 1rem; font-weight: 600; cursor: pointer; margin-top: 1rem; }
        button:hover { opacity: 0.9; }
        .checkbox { display: flex; align-items: center; gap: 0.5rem; }
        .checkbox input { width: auto; }
    </style>
</head>
<body>
    <div class="header">
        <h1>⚽ Configuration</h1>
        <a href="/admin/logout">Logout</a>
    </div>
    <div class="container">
        <div class="nav">
            <a href="/admin">Dashboard</a>
            <a href="/admin/config" class="active">Configuration</a>
            <a href="/admin/users">Users</a>
        </div>

        <form method="POST">
            {% for category, items in config.items() %}
            <div class="card">
                <h2>{{ category }}</h2>
                {% for key, item in items.items() %}
                <div class="form-group">
                    <label>{{ key }}</label>
                    <div class="description">{{ item.description }}</div>
                    {% if item.type == 'bool' %}
                    <div class="checkbox">
                        <input type="checkbox" name="{{ key }}" value="true" {% if item.value %}checked{% endif %}>
                        <span>Enabled</span>
                    </div>
                    {% elif item.type == 'select' %}
                    <select name="{{ key }}">
                        {% for opt in item.options %}
                        <option value="{{ opt }}" {% if item.raw_value == opt %}selected{% endif %}>{{ opt }}</option>
                        {% endfor %}
                    </select>
                    {% elif item.type == 'password' %}
                    <input type="password" name="{{ key }}" placeholder="••••••••">
                    {% else %}
                    <input type="text" name="{{ key }}" value="{{ item.raw_value or '' }}">
                    {% endif %}
                </div>
                {% endfor %}
            </div>
            {% endfor %}
            <button type="submit">Save Configuration</button>
        </form>
    </div>
</body>
</html>
"""

ADMIN_USERS_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Users - Soccer Rig Admin</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0f172a; color: #f1f5f9; min-height: 100vh; }
        .header { background: #1e293b; padding: 1rem 2rem; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; }
        .header h1 { font-size: 1.25rem; }
        .header a { color: #94a3b8; text-decoration: none; }
        .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
        .nav { display: flex; gap: 1rem; margin-bottom: 2rem; }
        .nav a { padding: 0.75rem 1.5rem; background: #1e293b; border-radius: 0.5rem; color: #f1f5f9; text-decoration: none; }
        .nav a:hover, .nav a.active { background: #6366f1; }
        .card { background: #1e293b; border-radius: 1rem; padding: 1.5rem; margin-bottom: 1.5rem; }
        .card h2 { font-size: 1.125rem; margin-bottom: 1rem; color: #6366f1; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 0.75rem; text-align: left; border-bottom: 1px solid #334155; }
        th { color: #94a3b8; font-weight: 500; }
        .badge { padding: 0.25rem 0.5rem; border-radius: 0.25rem; font-size: 0.75rem; }
        .badge-success { background: #10b981; color: white; }
        .badge-warning { background: #f59e0b; color: white; }
        .badge-info { background: #6366f1; color: white; }
        .btn { padding: 0.5rem 0.75rem; border-radius: 0.375rem; font-size: 0.75rem; cursor: pointer; border: none; }
        .btn-danger { background: #ef4444; color: white; }
        .btn-secondary { background: #334155; color: white; }
        .btn:hover { opacity: 0.9; }
        .actions { display: flex; gap: 0.5rem; }
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); justify-content: center; align-items: center; z-index: 1000; }
        .modal.active { display: flex; }
        .modal-content { background: #1e293b; padding: 2rem; border-radius: 1rem; width: 100%; max-width: 500px; }
        .modal h3 { margin-bottom: 1.5rem; }
        .form-group { margin-bottom: 1rem; }
        .form-group label { display: block; margin-bottom: 0.25rem; color: #94a3b8; }
        .form-group input, .form-group select { width: 100%; padding: 0.5rem; border: 1px solid #334155; border-radius: 0.375rem; background: #0f172a; color: white; }
        .modal-actions { display: flex; gap: 1rem; margin-top: 1.5rem; }
        .btn-primary { background: #6366f1; color: white; padding: 0.75rem 1.5rem; }
    </style>
</head>
<body>
    <div class="header">
        <h1>⚽ User Management</h1>
        <a href="/admin/logout">Logout</a>
    </div>
    <div class="container">
        <div class="nav">
            <a href="/admin">Dashboard</a>
            <a href="/admin/config">Configuration</a>
            <a href="/admin/users" class="active">Users</a>
        </div>

        <div class="card">
            <h2>Registered Users ({{ users|length }})</h2>
            <table>
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Email</th>
                        <th>Role</th>
                        <th>TeamSnap</th>
                        <th>Created</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {% for user in users %}
                    <tr data-user-id="{{ user.id }}">
                        <td>{{ user.first_name }} {{ user.last_name }}</td>
                        <td>{{ user.email }}</td>
                        <td><span class="badge badge-info">{{ user.role }}</span></td>
                        <td>
                            {% if user.teamsnap_connected %}
                            <span class="badge badge-success">Connected</span>
                            {% else %}
                            <span class="badge badge-warning">Not connected</span>
                            {% endif %}
                        </td>
                        <td>{{ user.created_at[:10] if user.created_at else '-' }}</td>
                        <td class="actions">
                            <button class="btn btn-secondary" onclick="editUser({{ user.id }})">Edit</button>
                            <button class="btn btn-secondary" onclick="resetPassword({{ user.id }})">Reset PW</button>
                            <button class="btn btn-danger" onclick="deleteUser({{ user.id }}, '{{ user.email }}')">Delete</button>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <div class="modal" id="edit-modal">
        <div class="modal-content">
            <h3>Edit User</h3>
            <input type="hidden" id="edit-user-id">
            <div class="form-group">
                <label>First Name</label>
                <input type="text" id="edit-first-name">
            </div>
            <div class="form-group">
                <label>Last Name</label>
                <input type="text" id="edit-last-name">
            </div>
            <div class="form-group">
                <label>Email</label>
                <input type="email" id="edit-email">
            </div>
            <div class="form-group">
                <label>Phone</label>
                <input type="tel" id="edit-phone">
            </div>
            <div class="form-group">
                <label>Role</label>
                <select id="edit-role">
                    <option value="parent">Parent</option>
                    <option value="player">Player</option>
                    <option value="coach">Coach</option>
                    <option value="family">Family</option>
                    <option value="admin">Admin</option>
                </select>
            </div>
            <div class="modal-actions">
                <button class="btn btn-primary" onclick="saveUser()">Save</button>
                <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
            </div>
        </div>
    </div>

    <script>
        async function editUser(userId) {
            const res = await fetch(`/api/admin/users/${userId}`);
            const user = await res.json();
            
            document.getElementById('edit-user-id').value = userId;
            document.getElementById('edit-first-name').value = user.first_name || '';
            document.getElementById('edit-last-name').value = user.last_name || '';
            document.getElementById('edit-email').value = user.email || '';
            document.getElementById('edit-phone').value = user.phone || '';
            document.getElementById('edit-role').value = user.role || 'parent';
            
            document.getElementById('edit-modal').classList.add('active');
        }
        
        async function saveUser() {
            const userId = document.getElementById('edit-user-id').value;
            const data = {
                first_name: document.getElementById('edit-first-name').value,
                last_name: document.getElementById('edit-last-name').value,
                email: document.getElementById('edit-email').value,
                phone: document.getElementById('edit-phone').value,
                role: document.getElementById('edit-role').value
            };
            
            await fetch(`/api/admin/users/${userId}`, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            });
            
            location.reload();
        }
        
        async function resetPassword(userId) {
            if (!confirm('Reset password for this user? A new password will be shown.')) return;
            
            const res = await fetch(`/api/admin/users/${userId}/reset-password`, { method: 'POST' });
            const data = await res.json();
            
            if (data.new_password) {
                alert(`New password: ${data.new_password}\\n\\nPlease share this with the user securely.`);
            }
        }
        
        async function deleteUser(userId, email) {
            if (!confirm(`Delete user ${email}? This cannot be undone.`)) return;
            
            await fetch(`/api/admin/users/${userId}`, { method: 'DELETE' });
            location.reload();
        }
        
        function closeModal() {
            document.getElementById('edit-modal').classList.remove('active');
        }
        
        // Close modal on backdrop click
        document.getElementById('edit-modal').addEventListener('click', (e) => {
            if (e.target.id === 'edit-modal') closeModal();
        });
    </script>
</body>
</html>
"""
