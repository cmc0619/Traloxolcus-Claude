"""
Authentication - Unified Login System

Simple authentication for all user types:
- Parents, players, coaches
- User type tracked but functionality is shared
- Dashboard adapts based on user type
"""

import os
import secrets
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional
from flask import Flask, request, session, jsonify, redirect, url_for, render_template_string
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# Authentication Helpers
# =============================================================================

def login_required(f):
    """Decorator to require login."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if request.is_json:
                return jsonify({'error': 'Authentication required'}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def get_current_user(db):
    """Get the current logged-in user."""
    if 'user_id' not in session:
        return None
    from .models import User
    return db.query(User).get(session['user_id'])


def get_user_team_ids(db, user_id: int) -> set:
    """Get all team IDs a user has access to.
    
    Access is granted through:
    - Teams the user coaches (coached_teams)
    - Teams the user follows (followed_teams)  
    - Teams their children are on (via parent_player -> team_player)
    - Admin users have access to all teams
    
    Returns set of team IDs.
    """
    from .models import User, Team
    
    user = db.query(User).get(user_id)
    if not user:
        return set()
    
    # Admins can see everything
    if user.role.value == 'admin':
        return {t.id for t in db.query(Team).all()}
    
    team_ids = set()
    
    # Teams user coaches
    for team in user.coached_teams:
        team_ids.add(team.id)
    
    # Teams user follows
    for team in user.followed_teams:
        team_ids.add(team.id)
    
    # Teams user's children are on
    for child in user.children:
        for team in child.teams:
            team_ids.add(team.id)
    
    return team_ids


# =============================================================================
# Flask Routes
# =============================================================================

def register_auth_routes(app: Flask, db):
    """Register authentication routes."""

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        """Login page."""
        from .models import User

        if request.method == 'POST':
            email = request.form.get('email', '').lower().strip()
            password = request.form.get('password', '')

            user = db.query(User).filter(User.email == email).first()

            if user and user.check_password(password):
                session['user_id'] = user.id
                session['user_email'] = user.email
                session['user_name'] = user.full_name
                session['user_role'] = user.role.value
                user.last_login = datetime.utcnow()
                db.commit()

                next_url = request.args.get('next', url_for('dashboard'))
                return redirect(next_url)
            else:
                return render_template_string(LOGIN_HTML, error='Invalid email or password')

        return render_template_string(LOGIN_HTML, error=None)

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        """Registration page."""
        from .models import User, UserRole

        if request.method == 'POST':
            email = request.form.get('email', '').lower().strip()
            password = request.form.get('password', '')
            confirm = request.form.get('confirm_password', '')
            first_name = request.form.get('first_name', '').strip()
            last_name = request.form.get('last_name', '').strip()
            user_type = request.form.get('user_type', 'parent')

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

            # Map user type to role
            role_map = {
                'parent': UserRole.PARENT,
                'family': UserRole.FAMILY,
                'player': UserRole.PLAYER,
                'coach': UserRole.COACH
            }
            role = role_map.get(user_type, UserRole.PARENT)

            # Create user
            user = User(
                email=email,
                first_name=first_name,
                last_name=last_name,
                role=role
            )
            user.set_password(password)
            db.add(user)
            db.commit()

            # Auto-login
            session['user_id'] = user.id
            session['user_email'] = user.email
            session['user_name'] = user.full_name
            session['user_role'] = user.role.value

            return redirect(url_for('dashboard'))

        return render_template_string(REGISTER_HTML, errors=None)

    @app.route('/logout')
    def logout():
        """Logout."""
        session.clear()
        return redirect(url_for('login'))

    @app.route('/dashboard')
    @login_required
    def dashboard():
        """User dashboard - adapts to user type."""
        from .models import User, Player, GameEvent, Clip, Game

        user = db.query(User).get(session['user_id'])

        # Get linked players (children for parents, self for players)
        linked_players = []

        if user.role.value in ('parent', 'family'):
            # Parents and family see linked children
            for child in user.children:
                linked_players.append(_get_player_data(db, child))
        elif user.role.value == 'player':
            # Players see themselves (if linked to a Player record)
            # Check if there's a player with matching email or linked
            player = db.query(Player).filter(
                Player.first_name == user.first_name,
                Player.last_name == user.last_name
            ).first()
            if player:
                linked_players.append(_get_player_data(db, player))
        elif user.role.value == 'coach':
            # Coaches see all players on their teams
            for team in user.coached_teams:
                for player in team.players:
                    if not any(p['player'].id == player.id for p in linked_players):
                        linked_players.append(_get_player_data(db, player))

        return render_template_string(
            DASHBOARD_HTML,
            user=user,
            players=linked_players
        )

    @app.route('/settings', methods=['GET', 'POST'])
    @login_required
    def settings():
        """User settings - notification preferences and TeamSnap integration."""
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
            new_email = request.form.get('email', '').strip()
            if new_email and new_email != user.email:
                user.email = new_email

            # Update TeamSnap credentials
            teamsnap_client_id = request.form.get('teamsnap_client_id', '').strip()
            teamsnap_client_secret = request.form.get('teamsnap_client_secret', '').strip()
            if teamsnap_client_id:
                user.teamsnap_client_id = teamsnap_client_id
            if teamsnap_client_secret:
                user.teamsnap_client_secret = teamsnap_client_secret

            db.commit()
            return redirect(url_for('settings') + '?saved=1')

        # Build callback URL for TeamSnap OAuth (proxy-safe)
        callback_url = url_for('teamsnap_callback', _external=True)
        
        return render_template_string(SETTINGS_HTML, user=user, callback_url=callback_url)

    @app.route('/teamsnap')
    @login_required
    def teamsnap_page():
        """Dedicated TeamSnap management page."""
        from .models import User, Team, Player
        
        user = db.query(User).get(session['user_id'])
        
        # Get teams the user has access to
        teams = []
        if user.teamsnap_token:
            # Teams user coaches
            for team in user.coached_teams:
                teams.append({
                    'id': team.id,
                    'name': team.name,
                    'team_code': team.team_code,
                    'season': team.season,
                    'player_count': len(team.players),
                    'last_sync': team.teamsnap_last_sync.isoformat() if team.teamsnap_last_sync else None
                })
            
            # Teams with user's children
            for child in user.children:
                for team in child.teams:
                    if not any(t['id'] == team.id for t in teams):
                        teams.append({
                            'id': team.id,
                            'name': team.name,
                            'team_code': team.team_code,
                            'season': team.season,
                            'player_count': len(team.players),
                            'last_sync': team.teamsnap_last_sync.isoformat() if team.teamsnap_last_sync else None
                        })
        
        # Get linked children
        children = [{
            'id': c.id,
            'name': c.full_name,
            'birth_year': c.birth_year,
            'teams': [t.name for t in c.teams]
        } for c in user.children]
        
        callback_url = url_for('teamsnap_callback', _external=True)
        
        return render_template_string(
            TEAMSNAP_HTML,
            user=user,
            teams=teams,
            children=children,
            callback_url=callback_url
        )

    @app.route('/player/<int:player_id>')
    @login_required
    def player_profile(player_id: int):
        """Player profile page with stats and clips."""
        from .models import User, Player, GameEvent, Clip, Game

        user = db.query(User).get(session['user_id'])
        player = db.query(Player).get(player_id)

        if not player:
            return "Player not found", 404

        # Access control: parents/family see children, players see self, coaches see team
        has_access = False
        if user.role.value in ('parent', 'family') and player in user.children:
            has_access = True
        elif user.role.value == 'player':
            # Player can see their own profile
            if player.first_name == user.first_name and player.last_name == user.last_name:
                has_access = True
        elif user.role.value == 'coach':
            for team in user.coached_teams:
                if player in team.players:
                    has_access = True
                    break
        elif user.role.value == 'admin':
            has_access = True

        if not has_access:
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
            stats=stats,
            user=user
        )

    # -------------------------------------------------------------------------
    # API Endpoints
    # -------------------------------------------------------------------------

    @app.route('/api/user/me')
    @login_required
    def api_current_user():
        """Get current user info."""
        from .models import User

        user = db.query(User).get(session['user_id'])

        return jsonify({
            'id': user.id,
            'email': user.email,
            'name': user.full_name,
            'role': user.role.value,
            'children_count': len(user.children),
            'teams_count': len(user.coached_teams)
        })

    @app.route('/api/user/players')
    @login_required
    def api_get_players():
        """Get all players linked to current user."""
        from .models import User, Player

        user = db.query(User).get(session['user_id'])
        players = []

        if user.role.value == 'parent':
            players = user.children
        elif user.role.value == 'coach':
            for team in user.coached_teams:
                for player in team.players:
                    if player not in players:
                        players.append(player)

        return jsonify({
            'players': [
                {
                    'id': p.id,
                    'name': p.full_name,
                    'birth_year': p.birth_year,
                    'teams': [
                        {'id': t.id, 'name': t.name, 'season': t.season}
                        for t in p.teams
                    ]
                }
                for p in players
            ]
        })

    @app.route('/api/user/notifications', methods=['GET', 'PUT'])
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


def _get_player_data(db, player):
    """Get player data with recent clips and events."""
    from .models import GameEvent, Clip, Game

    recent_clips = db.query(Clip, Game).join(
        Game, Clip.game_id == Game.id
    ).join(
        GameEvent, Clip.event_id == GameEvent.id
    ).filter(
        GameEvent.player_id == player.id
    ).order_by(Clip.created_at.desc()).limit(5).all()

    return {
        'player': player,
        'teams': list(player.teams),
        'recent_clips': [(c, g) for c, g in recent_clips],
        'clip_count': len(recent_clips)
    }


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
        <div class="logo">Soccer Rig</div>
        <div class="tagline">Sign in to your account</div>
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
        input, select { width: 100%; padding: 0.875rem 1rem; border: 2px solid #e2e8f0; border-radius: 0.5rem; font-size: 1rem; background: white; }
        input:focus, select:focus { outline: none; border-color: #10b981; }
        button { width: 100%; padding: 1rem; background: linear-gradient(135deg, #10b981, #059669); color: white; border: none; border-radius: 0.5rem; font-size: 1rem; font-weight: 600; cursor: pointer; }
        .error-list { background: #fee2e2; color: #dc2626; padding: 0.75rem; border-radius: 0.5rem; margin-bottom: 1rem; }
        .error-list li { margin-left: 1rem; }
        .login-link { text-align: center; margin-top: 1.5rem; color: #64748b; }
        .login-link a { color: #10b981; font-weight: 600; text-decoration: none; }
        .user-type-info { font-size: 0.75rem; color: #64748b; margin-top: 0.25rem; }
    </style>
</head>
<body>
    <div class="register-box">
        <div class="logo">Soccer Rig</div>
        <div class="tagline">Create your account</div>
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
                <label>I am a...</label>
                <select name="user_type">
                    <option value="parent">Parent / Guardian</option>
                    <option value="family">Family Member</option>
                    <option value="player">Player</option>
                    <option value="coach">Coach</option>
                </select>
                <div class="user-type-info">This helps us personalize your experience</div>
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
    <title>Dashboard - Soccer Rig</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f0f4f8; color: #1a202c; min-height: 100vh; }
        .header { background: linear-gradient(135deg, #1a472a 0%, #2d5a27 100%); color: white; padding: 1.5rem 2rem; }
        .header-content { max-width: 1200px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; }
        .header h1 { font-size: 1.5rem; }
        .header-nav a { color: white; margin-left: 1.5rem; text-decoration: none; opacity: 0.9; }
        .header-nav a:hover { opacity: 1; }
        .user-badge { background: rgba(255,255,255,0.2); padding: 0.25rem 0.75rem; border-radius: 1rem; font-size: 0.75rem; margin-left: 0.75rem; }
        .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
        .welcome { margin-bottom: 2rem; }
        .welcome h2 { font-size: 1.75rem; margin-bottom: 0.5rem; }
        .welcome p { color: #64748b; }
        .no-players { background: white; padding: 3rem; border-radius: 1rem; text-align: center; }
        .no-players h3 { margin-bottom: 1rem; }
        .no-players p { color: #64748b; margin-bottom: 1.5rem; }
        .no-players a { background: #10b981; color: white; padding: 0.75rem 1.5rem; border-radius: 0.5rem; text-decoration: none; }
        .player-card { background: white; border-radius: 1rem; padding: 1.5rem; margin-bottom: 1.5rem; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }
        .player-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; border-bottom: 1px solid #e2e8f0; padding-bottom: 1rem; }
        .player-name { font-size: 1.25rem; font-weight: 700; }
        .player-teams { color: #64748b; font-size: 0.875rem; }
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
            <h1>Soccer Rig <span class="user-badge">{{ user.role.value }}</span></h1>
            <nav class="header-nav">
                <a href="/settings">Settings</a>
                <a href="/logout">Logout</a>
            </nav>
        </div>
    </div>
    <div class="container">
        <div class="welcome">
            <h2>Welcome, {{ user.first_name }}!</h2>
            <p>{% if user.role.value == 'parent' %}View your children's soccer clips and highlights.{% elif user.role.value == 'player' %}View your clips and stats.{% elif user.role.value == 'coach' %}View your team's clips and player stats.{% endif %}</p>
        </div>

        {% if not players %}
        <div class="no-players">
            <h3>No Players Linked</h3>
            <p>{% if user.role.value == 'parent' %}Connect your TeamSnap account to automatically link your children.{% elif user.role.value == 'coach' %}Your team will appear here once configured.{% else %}Your player profile will appear here once linked.{% endif %}</p>
            <a href="/auth/teamsnap">Connect TeamSnap</a>
        </div>
        {% else %}
            {% for player_data in players %}
            <div class="player-card">
                <div class="player-header">
                    <div>
                        <div class="player-name">{{ player_data.player.full_name }}</div>
                        <div class="player-teams">
                            {% for team in player_data.teams %}
                                {{ team.name }}{% if not loop.last %}, {% endif %}
                            {% endfor %}
                        </div>
                    </div>
                    <a href="/player/{{ player_data.player.id }}" class="view-all">View All</a>
                </div>

                {% if player_data.recent_clips %}
                <div class="clips-grid">
                    {% for clip, game in player_data.recent_clips %}
                    <div class="clip-card">
                        <div class="clip-thumb">clip</div>
                        <div class="clip-info">
                            <div class="clip-title">{{ clip.title }}</div>
                            <div class="clip-meta">{{ game.opponent }} - {{ game.game_date.strftime('%b %d') if game.game_date else '' }}</div>
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
        .role-badge { display: inline-block; background: #e2e8f0; padding: 0.25rem 0.75rem; border-radius: 1rem; font-size: 0.75rem; color: #64748b; }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-content">
            <h1>Settings</h1>
            <a href="/dashboard" style="color: white; text-decoration: none;">Back to Dashboard</a>
        </div>
    </div>
    <div class="container">
        {% if request.args.get('saved') %}
        <div class="saved">Settings saved successfully!</div>
        {% endif %}

        <form method="POST">
            <div class="card">
                <h2>Profile <span class="role-badge">{{ user.role.value }}</span></h2>
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
                    <label>Email</label>
                    <input type="email" name="email" value="{{ user.email }}">
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
                        <span>A goal is scored</span>
                    </div>
                    <div class="checkbox">
                        <input type="checkbox" name="notify_saves" {% if user.notify_saves %}checked{% endif %}>
                        <span>A save is made (goalkeepers)</span>
                    </div>
                    <div class="checkbox">
                        <input type="checkbox" name="notify_highlights" {% if user.notify_highlights %}checked{% endif %}>
                        <span>Highlight reels are ready</span>
                    </div>
            </div>

            <div class="card">
                <h2>TeamSnap Integration</h2>
                <p style="color: #64748b; margin-bottom: 1rem;">Connect your TeamSnap account to automatically sync rosters and schedules.</p>
                
                {% if user.teamsnap_token %}
                <div style="background: #d1fae5; padding: 0.75rem; border-radius: 0.5rem; margin-bottom: 1rem; display: flex; justify-content: space-between; align-items: center;">
                    <span style="color: #059669;">✓ Connected to TeamSnap</span>
                    <div>
                        <a href="/teamsnap" style="color: #10b981; font-size: 0.875rem; margin-right: 1rem;">Manage →</a>
                        <a href="/auth/teamsnap/disconnect" style="color: #dc2626; font-size: 0.875rem;">Disconnect</a>
                    </div>
                </div>
                {% else %}
                <div style="background: #fef3c7; padding: 1rem; border-radius: 0.5rem; margin-bottom: 1rem;">
                    <strong style="color: #92400e;">Setup Required:</strong>
                    <ol style="color: #92400e; margin-left: 1.5rem; margin-top: 0.5rem; font-size: 0.875rem;">
                        <li>Go to <a href="https://auth.teamsnap.com/oauth/applications" target="_blank" style="color: #1a472a;">TeamSnap OAuth Applications</a></li>
                        <li>Click "New Application"</li>
                        <li>Enter any name (e.g., "Soccer Rig")</li>
                        <li>Set Redirect URI to: <code style="background: #fef9c3; padding: 0.25rem;">{{ callback_url }}</code></li>
                        <li>Copy your Client ID and Secret below</li>
                    </ol>
                </div>
                {% endif %}
                
                <div class="form-group">
                    <label>TeamSnap Client ID</label>
                    <input type="text" name="teamsnap_client_id" value="{{ user.teamsnap_client_id or '' }}" placeholder="Your OAuth Client ID">
                </div>
                <div class="form-group">
                    <label>TeamSnap Client Secret</label>
                    <input type="password" name="teamsnap_client_secret" value="{{ user.teamsnap_client_secret or '' }}" placeholder="Your OAuth Client Secret">
                </div>
                
                {% if user.teamsnap_client_id and user.teamsnap_client_secret and not user.teamsnap_token %}
                <a href="/auth/teamsnap" class="btn" style="display: inline-block; background: #10b981; color: white; padding: 0.75rem 1.5rem; border-radius: 0.5rem; text-decoration: none; text-align: center;">
                    Connect TeamSnap
                </a>
                {% endif %}
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
            <a href="/dashboard" style="color: white; opacity: 0.8; text-decoration: none; display: inline-block; margin-bottom: 1rem;">Back to Dashboard</a>
            <div class="player-name">{{ player.full_name }}</div>
            <div class="player-meta">Born {{ player.birth_year }} - {{ player.teams|length }} team(s)</div>
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
                    <div class="clip-thumb">clip</div>
                    <div class="clip-info">
                        <div class="clip-title">{{ clip.title }}</div>
                        <div class="clip-meta">{{ game.opponent }} - {{ game.game_date.strftime('%b %d, %Y') if game.game_date else '' }}</div>
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

TEAMSNAP_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TeamSnap - Soccer Rig</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f0f4f8; color: #1a202c; min-height: 100vh; }
        .header { background: linear-gradient(135deg, #1a472a 0%, #2d5a27 100%); color: white; padding: 1.5rem 2rem; }
        .header-content { max-width: 800px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; }
        .header h1 { font-size: 1.5rem; }
        .header a { color: white; text-decoration: none; opacity: 0.8; }
        .container { max-width: 800px; margin: 0 auto; padding: 2rem; }
        .card { background: white; border-radius: 1rem; padding: 1.5rem; margin-bottom: 1.5rem; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
        .card h2 { font-size: 1.125rem; margin-bottom: 1rem; color: #1a472a; }
        .status-connected { background: #d1fae5; color: #059669; padding: 0.75rem 1rem; border-radius: 0.5rem; display: flex; justify-content: space-between; align-items: center; }
        .status-disconnected { background: #fef3c7; color: #92400e; padding: 0.75rem 1rem; border-radius: 0.5rem; }
        .btn { padding: 0.625rem 1.25rem; border-radius: 0.5rem; font-size: 0.875rem; font-weight: 600; cursor: pointer; border: none; text-decoration: none; display: inline-block; }
        .btn-primary { background: #10b981; color: white; }
        .btn-secondary { background: #e2e8f0; color: #475569; }
        .btn-danger { background: #ef4444; color: white; }
        .btn:hover { opacity: 0.9; }
        .team-list { display: grid; gap: 0.75rem; }
        .team-item { background: #f8fafc; padding: 1rem; border-radius: 0.5rem; display: flex; justify-content: space-between; align-items: center; }
        .team-name { font-weight: 600; }
        .team-meta { color: #64748b; font-size: 0.875rem; }
        .badge { padding: 0.25rem 0.5rem; border-radius: 0.25rem; font-size: 0.75rem; background: #e2e8f0; color: #475569; }
        .children-list { display: grid; gap: 0.5rem; }
        .child-item { padding: 0.75rem; background: #f8fafc; border-radius: 0.5rem; }
        .child-name { font-weight: 600; }
        .child-teams { font-size: 0.875rem; color: #64748b; }
        .setup-steps { background: #fef3c7; padding: 1rem; border-radius: 0.5rem; margin-bottom: 1rem; }
        .setup-steps ol { margin-left: 1.25rem; color: #92400e; font-size: 0.875rem; }
        .setup-steps code { background: #fef9c3; padding: 0.125rem 0.25rem; border-radius: 0.25rem; }
        .form-group { margin-bottom: 1rem; }
        .form-group label { display: block; margin-bottom: 0.25rem; font-weight: 500; color: #374151; }
        .form-group input { width: 100%; padding: 0.625rem; border: 1px solid #d1d5db; border-radius: 0.375rem; font-size: 0.875rem; }
        .nav-link { display: inline-block; margin-bottom: 1rem; color: #10b981; text-decoration: none; }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-content">
            <h1>TeamSnap</h1>
            <a href="/dashboard">Back to Dashboard</a>
        </div>
    </div>
    <div class="container">
        <a href="/settings" class="nav-link">← Settings</a>
        
        <div class="card">
            <h2>Connection Status</h2>
            {% if user.teamsnap_token %}
            <div class="status-connected">
                <span>✓ Connected to TeamSnap</span>
                <div>
                    <button class="btn btn-secondary" onclick="syncTeams()">Sync Now</button>
                    <a href="/auth/teamsnap/disconnect" class="btn btn-danger">Disconnect</a>
                </div>
            </div>
            {% else %}
            <div class="status-disconnected">
                <strong>Not Connected</strong>
                <p style="margin-top: 0.5rem;">Set up your TeamSnap credentials to sync rosters and schedules.</p>
            </div>
            
            {% if not user.teamsnap_client_id %}
            <div class="setup-steps" style="margin-top: 1rem;">
                <strong>Setup Instructions:</strong>
                <ol>
                    <li>Go to <a href="https://auth.teamsnap.com/oauth/applications" target="_blank">TeamSnap OAuth Applications</a></li>
                    <li>Click "New Application"</li>
                    <li>Set Redirect URI to: <code>{{ callback_url }}</code></li>
                    <li>Copy your Client ID and Secret below</li>
                </ol>
            </div>
            
            <form method="POST" action="/settings">
                <div class="form-group">
                    <label>Client ID</label>
                    <input type="text" name="teamsnap_client_id" value="{{ user.teamsnap_client_id or '' }}" placeholder="Your OAuth Client ID">
                </div>
                <div class="form-group">
                    <label>Client Secret</label>
                    <input type="password" name="teamsnap_client_secret" value="{{ user.teamsnap_client_secret or '' }}" placeholder="Your OAuth Client Secret">
                </div>
                <button type="submit" class="btn btn-primary">Save Credentials</button>
            </form>
            {% else %}
            <div style="margin-top: 1rem;">
                <a href="/auth/teamsnap" class="btn btn-primary">Connect TeamSnap</a>
            </div>
            {% endif %}
            {% endif %}
        </div>

        {% if teams %}
        <div class="card">
            <h2>Synced Teams ({{ teams|length }})</h2>
            <div class="team-list">
                {% for team in teams %}
                <div class="team-item">
                    <div>
                        <div class="team-name">{{ team.name }}</div>
                        <div class="team-meta">{{ team.season or '' }} • {{ team.player_count }} players</div>
                    </div>
                    <span class="badge">{{ team.team_code or 'No code' }}</span>
                </div>
                {% endfor %}
            </div>
        </div>
        {% endif %}

        {% if children %}
        <div class="card">
            <h2>Linked Players ({{ children|length }})</h2>
            <div class="children-list">
                {% for child in children %}
                <div class="child-item">
                    <div class="child-name">{{ child.name }}</div>
                    <div class="child-teams">{{ child.teams|join(', ') if child.teams else 'No teams' }}</div>
                </div>
                {% endfor %}
            </div>
        </div>
        {% endif %}

        {% if not teams and user.teamsnap_token %}
        <div class="card">
            <h2>No Teams Yet</h2>
            <p style="color: #64748b; margin-bottom: 1rem;">You're connected but haven't synced any teams yet.</p>
            <button class="btn btn-primary" onclick="syncTeams()">Sync Teams</button>
        </div>
        {% endif %}
    </div>

    <script>
        async function syncTeams() {
            const btn = event.target;
            btn.disabled = true;
            btn.textContent = 'Syncing...';
            
            try {
                const res = await fetch('/api/teamsnap/sync', { method: 'POST' });
                const data = await res.json();
                if (data.error) {
                    alert('Sync failed: ' + data.error);
                } else {
                    location.reload();
                }
            } catch (e) {
                alert('Sync failed: ' + e.message);
            }
            
            btn.disabled = false;
            btn.textContent = 'Sync Now';
        }
    </script>
</body>
</html>
"""
