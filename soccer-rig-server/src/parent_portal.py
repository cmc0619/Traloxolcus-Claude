"""
Parent Portal - Authentication and Family Dashboard

Features:
- Parent registration and login
- Family dashboard showing all children's clips
- Per-child notification preferences
- Password reset via email
"""

import os
import secrets
import hashlib
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional, Dict, List
from flask import Flask, request, session, jsonify, redirect, url_for, render_template_string
from werkzeug.security import generate_password_hash, check_password_hash
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# Authentication Helpers
# =============================================================================

def login_required(f):
    """Decorator to require parent login."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if request.is_json:
                return jsonify({'error': 'Authentication required'}), 401
            return redirect(url_for('parent_login'))
        return f(*args, **kwargs)
    return decorated_function


def generate_token(length: int = 32) -> str:
    """Generate a secure random token."""
    return secrets.token_urlsafe(length)


# =============================================================================
# Flask Routes
# =============================================================================

def register_parent_routes(app: Flask, db):
    """Register parent portal routes."""

    @app.route('/login', methods=['GET', 'POST'])
    def parent_login():
        """Parent login page."""
        from .models import User

        if request.method == 'POST':
            email = request.form.get('email', '').lower().strip()
            password = request.form.get('password', '')

            user = db.query(User).filter(User.email == email).first()

            if user and user.check_password(password):
                session['user_id'] = user.id
                session['user_email'] = user.email
                session['user_name'] = user.full_name
                user.last_login = datetime.utcnow()
                db.commit()

                next_url = request.args.get('next', url_for('family_dashboard'))
                return redirect(next_url)
            else:
                return render_template_string(LOGIN_HTML, error='Invalid email or password')

        return render_template_string(LOGIN_HTML, error=None)

    @app.route('/register', methods=['GET', 'POST'])
    def parent_register():
        """Parent registration page."""
        from .models import User, UserRole

        if request.method == 'POST':
            email = request.form.get('email', '').lower().strip()
            password = request.form.get('password', '')
            confirm = request.form.get('confirm_password', '')
            first_name = request.form.get('first_name', '').strip()
            last_name = request.form.get('last_name', '').strip()

            # Validation
            errors = []
            if not email or '@' not in email:
                errors.append('Valid email required')
            if len(password) < 6:
                errors.append('Password must be at least 6 characters')
            if password != confirm:
                errors.append('Passwords do not match')
            if not first_name or not last_name:
                errors.append('First and last name required')

            # Check if email exists
            if db.query(User).filter(User.email == email).first():
                errors.append('Email already registered')

            if errors:
                return render_template_string(REGISTER_HTML, errors=errors)

            # Create user
            user = User(
                email=email,
                first_name=first_name,
                last_name=last_name,
                role=UserRole.PARENT
            )
            user.set_password(password)
            db.add(user)
            db.commit()

            # Auto-login
            session['user_id'] = user.id
            session['user_email'] = user.email
            session['user_name'] = user.full_name

            return redirect(url_for('family_dashboard'))

        return render_template_string(REGISTER_HTML, errors=None)

    @app.route('/logout')
    def parent_logout():
        """Logout."""
        session.clear()
        return redirect(url_for('parent_login'))

    @app.route('/dashboard')
    @login_required
    def family_dashboard():
        """Family dashboard - shows all children's clips."""
        from .models import User, Player, GameEvent, Clip, Game

        user = db.query(User).get(session['user_id'])

        # Get all children
        children_data = []
        for child in user.children:
            # Get recent clips for this child
            recent_clips = db.query(Clip, Game).join(
                Game, Clip.game_id == Game.id
            ).join(
                GameEvent, Clip.event_id == GameEvent.id
            ).filter(
                GameEvent.player_id == child.id
            ).order_by(Clip.created_at.desc()).limit(5).all()

            # Get recent events
            recent_events = db.query(GameEvent, Game).join(
                Game, GameEvent.game_id == Game.id
            ).filter(
                GameEvent.player_id == child.id
            ).order_by(GameEvent.id.desc()).limit(10).all()

            # Get stats
            from .services.statistics import StatisticsService
            stats_service = StatisticsService(db)

            children_data.append({
                'player': child,
                'teams': list(child.teams),
                'recent_clips': [(c, g) for c, g in recent_clips],
                'recent_events': [(e, g) for e, g in recent_events],
                'clip_count': len(recent_clips)
            })

        return render_template_string(
            DASHBOARD_HTML,
            user=user,
            children=children_data
        )

    @app.route('/settings', methods=['GET', 'POST'])
    @login_required
    def parent_settings():
        """Parent settings - notification preferences."""
        from .models import User, NotificationFrequency

        user = db.query(User).get(session['user_id'])

        if request.method == 'POST':
            # Update notification preferences
            user.notify_frequency = NotificationFrequency(
                request.form.get('notify_frequency', 'instant')
            )
            user.notify_goals = 'notify_goals' in request.form
            user.notify_saves = 'notify_saves' in request.form
            user.notify_highlights = 'notify_highlights' in request.form
            user.notify_game_ready = 'notify_game_ready' in request.form

            # Update profile
            user.first_name = request.form.get('first_name', user.first_name)
            user.last_name = request.form.get('last_name', user.last_name)
            user.phone = request.form.get('phone', user.phone)

            db.commit()
            return redirect(url_for('parent_settings') + '?saved=1')

        return render_template_string(SETTINGS_HTML, user=user)

    @app.route('/player/<int:player_id>')
    @login_required
    def player_profile(player_id: int):
        """Player profile page with stats and clips."""
        from .models import User, Player, GameEvent, Clip, Game, PlayerSeasonStats

        user = db.query(User).get(session['user_id'])
        player = db.query(Player).get(player_id)

        if not player:
            return "Player not found", 404

        # Verify parent has access to this player
        if player not in user.children:
            return "Access denied", 403

        # Get all clips
        clips = db.query(Clip, Game).join(
            Game, Clip.game_id == Game.id
        ).join(
            GameEvent, Clip.event_id == GameEvent.id
        ).filter(
            GameEvent.player_id == player_id
        ).order_by(Clip.created_at.desc()).all()

        # Get season stats
        from .services.statistics import StatisticsService
        stats_service = StatisticsService(db)
        stats = []
        for team in player.teams:
            team_stats = stats_service.get_player_season_stats(
                player_id, team.id, team.season or f"Season {datetime.now().year}"
            )
            if team_stats:
                stats.append({'team': team, 'stats': team_stats})

        return render_template_string(
            PLAYER_PROFILE_HTML,
            player=player,
            clips=clips,
            stats=stats
        )

    # -------------------------------------------------------------------------
    # API Endpoints
    # -------------------------------------------------------------------------

    @app.route('/api/parent/children')
    @login_required
    def api_get_children():
        """Get all children for current user."""
        from .models import User

        user = db.query(User).get(session['user_id'])

        return jsonify({
            'children': [
                {
                    'id': child.id,
                    'name': child.full_name,
                    'birth_year': child.birth_year,
                    'teams': [
                        {'id': t.id, 'name': t.name, 'season': t.season}
                        for t in child.teams
                    ]
                }
                for child in user.children
            ]
        })

    @app.route('/api/parent/clips')
    @login_required
    def api_get_family_clips():
        """Get recent clips for all children."""
        from .models import User, GameEvent, Clip, Game

        user = db.query(User).get(session['user_id'])
        child_ids = [c.id for c in user.children]

        if not child_ids:
            return jsonify({'clips': []})

        clips = db.query(Clip, Game, GameEvent).join(
            Game, Clip.game_id == Game.id
        ).join(
            GameEvent, Clip.event_id == GameEvent.id
        ).filter(
            GameEvent.player_id.in_(child_ids)
        ).order_by(Clip.created_at.desc()).limit(50).all()

        return jsonify({
            'clips': [
                {
                    'id': c.id,
                    'title': c.title,
                    'thumbnail': c.thumbnail_url,
                    'duration': c.duration_seconds,
                    'game_date': g.game_date.isoformat() if g.game_date else None,
                    'opponent': g.opponent,
                    'event_type': e.event_type.value if e.event_type else None,
                    'player_id': e.player_id
                }
                for c, g, e in clips
            ]
        })

    @app.route('/api/parent/notifications', methods=['GET', 'PUT'])
    @login_required
    def api_notifications():
        """Get or update notification preferences."""
        from .models import User, NotificationFrequency

        user = db.query(User).get(session['user_id'])

        if request.method == 'PUT':
            data = request.get_json()
            if 'frequency' in data:
                user.notify_frequency = NotificationFrequency(data['frequency'])
            if 'goals' in data:
                user.notify_goals = data['goals']
            if 'saves' in data:
                user.notify_saves = data['saves']
            if 'highlights' in data:
                user.notify_highlights = data['highlights']
            if 'game_ready' in data:
                user.notify_game_ready = data['game_ready']
            db.commit()

        return jsonify({
            'frequency': user.notify_frequency.value,
            'goals': user.notify_goals,
            'saves': user.notify_saves,
            'highlights': user.notify_highlights,
            'game_ready': user.notify_game_ready
        })


# =============================================================================
# HTML Templates
# =============================================================================

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - Soccer Rig</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: linear-gradient(135deg, #1a472a 0%, #2d5a27 100%); color: #f1f5f9; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 1rem; }
        .login-box { background: rgba(255,255,255,0.95); padding: 2.5rem; border-radius: 1rem; width: 100%; max-width: 400px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); color: #1a202c; }
        .logo { text-align: center; font-size: 2rem; margin-bottom: 0.5rem; }
        .tagline { text-align: center; color: #64748b; margin-bottom: 2rem; }
        .form-group { margin-bottom: 1.25rem; }
        label { display: block; margin-bottom: 0.5rem; font-weight: 500; color: #374151; }
        input { width: 100%; padding: 0.875rem 1rem; border: 2px solid #e2e8f0; border-radius: 0.5rem; font-size: 1rem; }
        input:focus { outline: none; border-color: #10b981; }
        button { width: 100%; padding: 1rem; background: linear-gradient(135deg, #10b981, #059669); color: white; border: none; border-radius: 0.5rem; font-size: 1rem; font-weight: 600; cursor: pointer; }
        button:hover { opacity: 0.9; }
        .error { background: #fee2e2; color: #dc2626; padding: 0.75rem; border-radius: 0.5rem; margin-bottom: 1rem; text-align: center; }
        .register-link { text-align: center; margin-top: 1.5rem; color: #64748b; }
        .register-link a { color: #10b981; font-weight: 600; text-decoration: none; }
    </style>
</head>
<body>
    <div class="login-box">
        <div class="logo">⚽</div>
        <div class="tagline">Soccer Rig Parent Portal</div>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        <form method="POST">
            <div class="form-group">
                <label>Email</label>
                <input type="email" name="email" required autofocus>
            </div>
            <div class="form-group">
                <label>Password</label>
                <input type="password" name="password" required>
            </div>
            <button type="submit">Sign In</button>
        </form>
        <div class="register-link">
            Don't have an account? <a href="/register">Register</a>
        </div>
    </div>
</body>
</html>
"""

REGISTER_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Register - Soccer Rig</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: linear-gradient(135deg, #1a472a 0%, #2d5a27 100%); color: #f1f5f9; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 1rem; }
        .register-box { background: rgba(255,255,255,0.95); padding: 2.5rem; border-radius: 1rem; width: 100%; max-width: 450px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); color: #1a202c; }
        .logo { text-align: center; font-size: 2rem; margin-bottom: 0.5rem; }
        .tagline { text-align: center; color: #64748b; margin-bottom: 2rem; }
        .form-group { margin-bottom: 1.25rem; }
        .form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
        label { display: block; margin-bottom: 0.5rem; font-weight: 500; color: #374151; }
        input { width: 100%; padding: 0.875rem 1rem; border: 2px solid #e2e8f0; border-radius: 0.5rem; font-size: 1rem; }
        input:focus { outline: none; border-color: #10b981; }
        button { width: 100%; padding: 1rem; background: linear-gradient(135deg, #10b981, #059669); color: white; border: none; border-radius: 0.5rem; font-size: 1rem; font-weight: 600; cursor: pointer; }
        .error-list { background: #fee2e2; color: #dc2626; padding: 0.75rem; border-radius: 0.5rem; margin-bottom: 1rem; }
        .error-list li { margin-left: 1rem; }
        .login-link { text-align: center; margin-top: 1.5rem; color: #64748b; }
        .login-link a { color: #10b981; font-weight: 600; text-decoration: none; }
    </style>
</head>
<body>
    <div class="register-box">
        <div class="logo">⚽</div>
        <div class="tagline">Create Your Account</div>
        {% if errors %}<div class="error-list"><ul>{% for e in errors %}<li>{{ e }}</li>{% endfor %}</ul></div>{% endif %}
        <form method="POST">
            <div class="form-row">
                <div class="form-group">
                    <label>First Name</label>
                    <input type="text" name="first_name" required>
                </div>
                <div class="form-group">
                    <label>Last Name</label>
                    <input type="text" name="last_name" required>
                </div>
            </div>
            <div class="form-group">
                <label>Email</label>
                <input type="email" name="email" required>
            </div>
            <div class="form-group">
                <label>Password</label>
                <input type="password" name="password" required minlength="6">
            </div>
            <div class="form-group">
                <label>Confirm Password</label>
                <input type="password" name="confirm_password" required>
            </div>
            <button type="submit">Create Account</button>
        </form>
        <div class="login-link">
            Already have an account? <a href="/login">Sign In</a>
        </div>
    </div>
</body>
</html>
"""

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Family Dashboard - Soccer Rig</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f0f4f8; color: #1a202c; min-height: 100vh; }
        .header { background: linear-gradient(135deg, #1a472a 0%, #2d5a27 100%); color: white; padding: 1.5rem 2rem; }
        .header-content { max-width: 1200px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; }
        .header h1 { font-size: 1.5rem; }
        .header-nav a { color: white; margin-left: 1.5rem; text-decoration: none; opacity: 0.9; }
        .header-nav a:hover { opacity: 1; }
        .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
        .welcome { margin-bottom: 2rem; }
        .welcome h2 { font-size: 1.75rem; margin-bottom: 0.5rem; }
        .welcome p { color: #64748b; }
        .no-children { background: white; padding: 3rem; border-radius: 1rem; text-align: center; }
        .no-children h3 { margin-bottom: 1rem; }
        .no-children p { color: #64748b; margin-bottom: 1.5rem; }
        .no-children a { background: #10b981; color: white; padding: 0.75rem 1.5rem; border-radius: 0.5rem; text-decoration: none; }
        .child-card { background: white; border-radius: 1rem; padding: 1.5rem; margin-bottom: 1.5rem; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }
        .child-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; border-bottom: 1px solid #e2e8f0; padding-bottom: 1rem; }
        .child-name { font-size: 1.25rem; font-weight: 700; }
        .child-teams { color: #64748b; font-size: 0.875rem; }
        .clips-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 1rem; }
        .clip-card { background: #f8fafc; border-radius: 0.5rem; overflow: hidden; }
        .clip-thumb { width: 100%; aspect-ratio: 16/9; background: #e2e8f0; display: flex; align-items: center; justify-content: center; font-size: 2rem; }
        .clip-info { padding: 0.75rem; }
        .clip-title { font-weight: 600; font-size: 0.875rem; }
        .clip-meta { color: #64748b; font-size: 0.75rem; }
        .view-all { display: inline-block; margin-top: 1rem; color: #10b981; text-decoration: none; font-weight: 600; }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-content">
            <h1>⚽ Family Dashboard</h1>
            <nav class="header-nav">
                <a href="/settings">Settings</a>
                <a href="/logout">Logout</a>
            </nav>
        </div>
    </div>
    <div class="container">
        <div class="welcome">
            <h2>Welcome, {{ user.first_name }}!</h2>
            <p>View your children's soccer clips and highlights.</p>
        </div>

        {% if not children %}
        <div class="no-children">
            <h3>No Players Linked</h3>
            <p>Connect your TeamSnap account to automatically link your children.</p>
            <a href="/auth/teamsnap">Connect TeamSnap</a>
        </div>
        {% else %}
            {% for child_data in children %}
            <div class="child-card">
                <div class="child-header">
                    <div>
                        <div class="child-name">{{ child_data.player.full_name }}</div>
                        <div class="child-teams">
                            {% for team in child_data.teams %}
                                {{ team.name }}{% if not loop.last %}, {% endif %}
                            {% endfor %}
                        </div>
                    </div>
                    <a href="/player/{{ child_data.player.id }}" class="view-all">View All →</a>
                </div>

                {% if child_data.recent_clips %}
                <div class="clips-grid">
                    {% for clip, game in child_data.recent_clips %}
                    <div class="clip-card">
                        <div class="clip-thumb">🎬</div>
                        <div class="clip-info">
                            <div class="clip-title">{{ clip.title }}</div>
                            <div class="clip-meta">{{ game.opponent }} • {{ game.game_date.strftime('%b %d') if game.game_date else '' }}</div>
                        </div>
                    </div>
                    {% endfor %}
                </div>
                {% else %}
                <p style="color: #64748b;">No clips yet. Clips will appear after games are recorded and processed.</p>
                {% endif %}
            </div>
            {% endfor %}
        {% endif %}
    </div>
</body>
</html>
"""

SETTINGS_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Settings - Soccer Rig</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f0f4f8; color: #1a202c; min-height: 100vh; }
        .header { background: linear-gradient(135deg, #1a472a 0%, #2d5a27 100%); color: white; padding: 1.5rem 2rem; }
        .header-content { max-width: 800px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; }
        .container { max-width: 800px; margin: 0 auto; padding: 2rem; }
        .card { background: white; border-radius: 1rem; padding: 2rem; margin-bottom: 1.5rem; }
        .card h2 { font-size: 1.25rem; margin-bottom: 1.5rem; padding-bottom: 0.75rem; border-bottom: 1px solid #e2e8f0; }
        .form-group { margin-bottom: 1.25rem; }
        .form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
        label { display: block; margin-bottom: 0.5rem; font-weight: 500; }
        input, select { width: 100%; padding: 0.75rem; border: 2px solid #e2e8f0; border-radius: 0.5rem; font-size: 1rem; }
        .checkbox { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.75rem; }
        .checkbox input { width: auto; }
        button { padding: 0.875rem 2rem; background: #10b981; color: white; border: none; border-radius: 0.5rem; font-size: 1rem; font-weight: 600; cursor: pointer; }
        .saved { background: #d1fae5; color: #059669; padding: 0.75rem; border-radius: 0.5rem; margin-bottom: 1rem; }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-content">
            <h1>⚽ Settings</h1>
            <a href="/dashboard" style="color: white; text-decoration: none;">← Back to Dashboard</a>
        </div>
    </div>
    <div class="container">
        {% if request.args.get('saved') %}
        <div class="saved">Settings saved successfully!</div>
        {% endif %}

        <form method="POST">
            <div class="card">
                <h2>Profile</h2>
                <div class="form-row">
                    <div class="form-group">
                        <label>First Name</label>
                        <input type="text" name="first_name" value="{{ user.first_name }}">
                    </div>
                    <div class="form-group">
                        <label>Last Name</label>
                        <input type="text" name="last_name" value="{{ user.last_name }}">
                    </div>
                </div>
                <div class="form-group">
                    <label>Phone</label>
                    <input type="tel" name="phone" value="{{ user.phone or '' }}">
                </div>
            </div>

            <div class="card">
                <h2>Notification Preferences</h2>
                <div class="form-group">
                    <label>Email Frequency</label>
                    <select name="notify_frequency">
                        <option value="instant" {% if user.notify_frequency.value == 'instant' %}selected{% endif %}>Instant</option>
                        <option value="daily" {% if user.notify_frequency.value == 'daily' %}selected{% endif %}>Daily Digest</option>
                        <option value="weekly" {% if user.notify_frequency.value == 'weekly' %}selected{% endif %}>Weekly Digest</option>
                        <option value="none" {% if user.notify_frequency.value == 'none' %}selected{% endif %}>None</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Notify me when:</label>
                    <div class="checkbox">
                        <input type="checkbox" name="notify_goals" {% if user.notify_goals %}checked{% endif %}>
                        <span>My child scores a goal</span>
                    </div>
                    <div class="checkbox">
                        <input type="checkbox" name="notify_saves" {% if user.notify_saves %}checked{% endif %}>
                        <span>My child makes a save (goalkeepers)</span>
                    </div>
                    <div class="checkbox">
                        <input type="checkbox" name="notify_highlights" {% if user.notify_highlights %}checked{% endif %}>
                        <span>Highlight reels are ready</span>
                    </div>
                    <div class="checkbox">
                        <input type="checkbox" name="notify_game_ready" {% if user.notify_game_ready %}checked{% endif %}>
                        <span>Game footage is ready to view</span>
                    </div>
                </div>
            </div>

            <button type="submit">Save Settings</button>
        </form>
    </div>
</body>
</html>
"""

PLAYER_PROFILE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ player.full_name }} - Soccer Rig</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f0f4f8; color: #1a202c; min-height: 100vh; }
        .header { background: linear-gradient(135deg, #1a472a 0%, #2d5a27 100%); color: white; padding: 2rem; }
        .header-content { max-width: 1200px; margin: 0 auto; }
        .player-name { font-size: 2rem; font-weight: 700; }
        .player-meta { opacity: 0.9; margin-top: 0.5rem; }
        .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 1rem; margin-bottom: 2rem; }
        .stat-card { background: white; padding: 1.25rem; border-radius: 0.75rem; text-align: center; }
        .stat-value { font-size: 2rem; font-weight: 700; color: #10b981; }
        .stat-label { color: #64748b; font-size: 0.75rem; text-transform: uppercase; }
        .section { margin-bottom: 2rem; }
        .section h2 { font-size: 1.25rem; margin-bottom: 1rem; }
        .clips-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 1rem; }
        .clip-card { background: white; border-radius: 0.75rem; overflow: hidden; }
        .clip-thumb { width: 100%; aspect-ratio: 16/9; background: #1a202c; display: flex; align-items: center; justify-content: center; color: white; font-size: 3rem; }
        .clip-info { padding: 1rem; }
        .clip-title { font-weight: 600; margin-bottom: 0.25rem; }
        .clip-meta { color: #64748b; font-size: 0.875rem; }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-content">
            <a href="/dashboard" style="color: white; opacity: 0.8; text-decoration: none; display: inline-block; margin-bottom: 1rem;">← Back to Dashboard</a>
            <div class="player-name">{{ player.full_name }}</div>
            <div class="player-meta">Born {{ player.birth_year }} • {{ player.teams|length }} team(s)</div>
        </div>
    </div>
    <div class="container">
        {% if stats %}
        <div class="section">
            <h2>Season Stats</h2>
            {% for s in stats %}
            <h3 style="color: #64748b; font-size: 0.875rem; margin-bottom: 0.5rem;">{{ s.team.name }}</h3>
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-value">{{ s.stats.games_played }}</div>
                    <div class="stat-label">Games</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{{ s.stats.goals }}</div>
                    <div class="stat-label">Goals</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{{ s.stats.assists }}</div>
                    <div class="stat-label">Assists</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{{ s.stats.shots }}</div>
                    <div class="stat-label">Shots</div>
                </div>
                {% if s.stats.saves %}
                <div class="stat-card">
                    <div class="stat-value">{{ s.stats.saves }}</div>
                    <div class="stat-label">Saves</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{{ s.stats.save_percentage|round(1) if s.stats.save_percentage else 0 }}%</div>
                    <div class="stat-label">Save %</div>
                </div>
                {% endif %}
            </div>
            {% endfor %}
        </div>
        {% endif %}

        <div class="section">
            <h2>All Clips ({{ clips|length }})</h2>
            {% if clips %}
            <div class="clips-grid">
                {% for clip, game in clips %}
                <div class="clip-card">
                    <div class="clip-thumb">🎬</div>
                    <div class="clip-info">
                        <div class="clip-title">{{ clip.title }}</div>
                        <div class="clip-meta">{{ game.opponent }} • {{ game.game_date.strftime('%b %d, %Y') if game.game_date else '' }}</div>
                    </div>
                </div>
                {% endfor %}
            </div>
            {% else %}
            <p style="color: #64748b;">No clips yet.</p>
            {% endif %}
        </div>
    </div>
</body>
</html>
"""
