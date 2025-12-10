"""
TeamSnap Integration for Soccer Rig

Provides OAuth2 authentication and roster synchronization with TeamSnap.
Uses the TeamSnap API v3 to pull team rosters, player info, and parent contacts.

OAuth Flow:
1. User clicks "Connect TeamSnap" -> redirected to TeamSnap auth
2. TeamSnap redirects back with authorization code
3. We exchange code for access token
4. Store token and sync roster

API Reference: https://www.teamsnap.com/documentation/apiv3
"""

import os
import requests
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlencode
import logging

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

TEAMSNAP_AUTH_URL = "https://auth.teamsnap.com/oauth/authorize"
TEAMSNAP_TOKEN_URL = "https://auth.teamsnap.com/oauth/token"
TEAMSNAP_API_URL = "https://api.teamsnap.com/v3"

# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class TeamSnapPlayer:
    """Player information from TeamSnap roster."""
    id: int
    first_name: str
    last_name: str
    jersey_number: Optional[str] = None
    position: Optional[str] = None
    is_goalkeeper: bool = False
    email_addresses: List[str] = field(default_factory=list)
    phone_numbers: List[str] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def display_name(self) -> str:
        """Format: '#7 - Marcus Johnson' or 'Marcus Johnson' if no number."""
        if self.jersey_number:
            return f"#{self.jersey_number} - {self.full_name}"
        return self.full_name


@dataclass
class TeamSnapTeam:
    """Team information from TeamSnap."""
    id: int
    name: str
    sport: str
    division_name: Optional[str] = None
    season_name: Optional[str] = None
    players: List[TeamSnapPlayer] = field(default_factory=list)


@dataclass
class TeamSnapToken:
    """OAuth token storage."""
    access_token: str
    refresh_token: str
    expires_at: datetime
    user_id: int

    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() >= self.expires_at

    def to_dict(self) -> Dict:
        return {
            'access_token': self.access_token,
            'refresh_token': self.refresh_token,
            'expires_at': self.expires_at.isoformat(),
            'user_id': self.user_id
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'TeamSnapToken':
        return cls(
            access_token=data['access_token'],
            refresh_token=data['refresh_token'],
            expires_at=datetime.fromisoformat(data['expires_at']),
            user_id=data['user_id']
        )


# =============================================================================
# TeamSnap Client
# =============================================================================

class TeamSnapClient:
    """
    TeamSnap API client with OAuth2 support.

    Usage:
        client = TeamSnapClient(client_id, client_secret, redirect_uri)

        # Get auth URL for user
        auth_url = client.get_auth_url(state="random-state")

        # After callback, exchange code for token
        token = client.exchange_code(code)

        # Use token to fetch data
        teams = client.get_teams(token)
        roster = client.get_roster(token, team_id)
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None
    ):
        self.client_id = client_id or os.getenv('TEAMSNAP_CLIENT_ID')
        self.client_secret = client_secret or os.getenv('TEAMSNAP_CLIENT_SECRET')
        self.redirect_uri = redirect_uri or os.getenv('TEAMSNAP_REDIRECT_URI')

        if not all([self.client_id, self.client_secret]):
            logger.warning("TeamSnap credentials not configured")

    @property
    def is_configured(self) -> bool:
        """Check if TeamSnap integration is properly configured."""
        return bool(self.client_id and self.client_secret)

    # -------------------------------------------------------------------------
    # OAuth Flow
    # -------------------------------------------------------------------------

    def get_auth_url(self, state: str) -> str:
        """
        Generate TeamSnap OAuth authorization URL.

        Args:
            state: Random string to prevent CSRF (store in session)

        Returns:
            URL to redirect user to for authorization
        """
        params = {
            'response_type': 'code',
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri,
            'scope': 'read',
            'state': state
        }
        return f"{TEAMSNAP_AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> TeamSnapToken:
        """
        Exchange authorization code for access token.

        Args:
            code: Authorization code from callback

        Returns:
            TeamSnapToken with access credentials
        """
        response = requests.post(TEAMSNAP_TOKEN_URL, data={
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'redirect_uri': self.redirect_uri
        })
        response.raise_for_status()
        data = response.json()

        # Get user ID
        user = self._api_request(data['access_token'], '/me')
        user_id = user['collection']['items'][0]['data'][0]['value']

        return TeamSnapToken(
            access_token=data['access_token'],
            refresh_token=data['refresh_token'],
            expires_at=datetime.utcnow() + timedelta(seconds=data['expires_in']),
            user_id=user_id
        )

    def refresh_token(self, token: TeamSnapToken) -> TeamSnapToken:
        """
        Refresh an expired access token.

        Args:
            token: Existing token with refresh_token

        Returns:
            New TeamSnapToken with fresh credentials
        """
        response = requests.post(TEAMSNAP_TOKEN_URL, data={
            'grant_type': 'refresh_token',
            'refresh_token': token.refresh_token,
            'client_id': self.client_id,
            'client_secret': self.client_secret
        })
        response.raise_for_status()
        data = response.json()

        return TeamSnapToken(
            access_token=data['access_token'],
            refresh_token=data.get('refresh_token', token.refresh_token),
            expires_at=datetime.utcnow() + timedelta(seconds=data['expires_in']),
            user_id=token.user_id
        )

    # -------------------------------------------------------------------------
    # API Methods
    # -------------------------------------------------------------------------

    def _api_request(
        self,
        access_token: str,
        endpoint: str,
        params: Optional[Dict] = None
    ) -> Dict:
        """Make authenticated API request."""
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        url = f"{TEAMSNAP_API_URL}{endpoint}"
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()

    def get_me(self, token: TeamSnapToken) -> Dict:
        """Get current user info."""
        if token.is_expired:
            token = self.refresh_token(token)
        return self._api_request(token.access_token, '/me')

    def get_teams(self, token: TeamSnapToken) -> List[TeamSnapTeam]:
        """
        Get all teams the user has access to.

        Returns:
            List of TeamSnapTeam objects
        """
        if token.is_expired:
            token = self.refresh_token(token)

        data = self._api_request(
            token.access_token,
            '/teams',
            params={'user_id': token.user_id}
        )

        teams = []
        for item in data.get('collection', {}).get('items', []):
            team_data = {d['name']: d['value'] for d in item['data']}
            teams.append(TeamSnapTeam(
                id=team_data['id'],
                name=team_data['name'],
                sport=team_data.get('sport_id', 'soccer'),
                division_name=team_data.get('division_name'),
                season_name=team_data.get('season_name')
            ))

        return teams

    def get_roster(self, token: TeamSnapToken, team_id: int) -> List[TeamSnapPlayer]:
        """
        Get full roster for a team including contact info.

        Args:
            token: Valid access token
            team_id: TeamSnap team ID

        Returns:
            List of TeamSnapPlayer objects with jersey numbers and contacts
        """
        if token.is_expired:
            token = self.refresh_token(token)

        # Get members
        members_data = self._api_request(
            token.access_token,
            '/members',
            params={'team_id': team_id}
        )

        players = []
        for item in members_data.get('collection', {}).get('items', []):
            member = {d['name']: d['value'] for d in item['data']}

            # Skip non-players (coaches, managers)
            if not member.get('is_non_player', False) == False:
                continue

            # Get contact info
            member_id = member['id']
            contacts = self._get_member_contacts(token, member_id)

            # Determine position
            position = member.get('position')
            is_gk = position and 'goal' in position.lower() if position else False

            players.append(TeamSnapPlayer(
                id=member_id,
                first_name=member.get('first_name', ''),
                last_name=member.get('last_name', ''),
                jersey_number=member.get('jersey_number'),
                position=position,
                is_goalkeeper=is_gk,
                email_addresses=contacts.get('emails', []),
                phone_numbers=contacts.get('phones', [])
            ))

        return players

    def _get_member_contacts(self, token: TeamSnapToken, member_id: int) -> Dict:
        """Get email and phone contacts for a member (including parents)."""
        try:
            data = self._api_request(
                token.access_token,
                '/contact_email_addresses',
                params={'member_id': member_id}
            )

            emails = []
            for item in data.get('collection', {}).get('items', []):
                contact = {d['name']: d['value'] for d in item['data']}
                if contact.get('email'):
                    emails.append(contact['email'])

            # Get phone numbers
            phone_data = self._api_request(
                token.access_token,
                '/contact_phone_numbers',
                params={'member_id': member_id}
            )

            phones = []
            for item in phone_data.get('collection', {}).get('items', []):
                contact = {d['name']: d['value'] for d in item['data']}
                if contact.get('phone_number'):
                    phones.append(contact['phone_number'])

            return {'emails': emails, 'phones': phones}
        except Exception as e:
            logger.warning(f"Failed to get contacts for member {member_id}: {e}")
            return {'emails': [], 'phones': []}

    def get_team_events(
        self,
        token: TeamSnapToken,
        team_id: int,
        started_after: Optional[datetime] = None
    ) -> List[Dict]:
        """
        Get upcoming events (games) for a team.

        Useful for auto-syncing roster before games.
        """
        if token.is_expired:
            token = self.refresh_token(token)

        params = {'team_id': team_id}
        if started_after:
            params['started_after'] = started_after.isoformat()

        data = self._api_request(token.access_token, '/events', params=params)

        events = []
        for item in data.get('collection', {}).get('items', []):
            event = {d['name']: d['value'] for d in item['data']}
            if event.get('is_game'):
                events.append({
                    'id': event['id'],
                    'name': event.get('name', 'Game'),
                    'start_date': event.get('start_date'),
                    'location': event.get('location_name'),
                    'opponent': event.get('opponent_name')
                })

        return events


# =============================================================================
# Flask Routes
# =============================================================================

def register_teamsnap_routes(app, db):
    """
    Register TeamSnap OAuth routes with Flask app.

    Routes:
        GET /auth/teamsnap - Start OAuth flow
        GET /auth/teamsnap/callback - OAuth callback
        GET /api/teamsnap/teams - List connected teams
        POST /api/teamsnap/sync/<team_id> - Sync roster
        DELETE /auth/teamsnap - Disconnect TeamSnap
    """
    from flask import redirect, request, session, jsonify, url_for
    import secrets

    client = TeamSnapClient()

    @app.route('/auth/teamsnap')
    def teamsnap_auth():
        """Start TeamSnap OAuth flow."""
        if not client.is_configured:
            return jsonify({'error': 'TeamSnap not configured'}), 503

        # Generate state for CSRF protection
        state = secrets.token_urlsafe(32)
        session['teamsnap_state'] = state

        # Get return URL if provided
        session['teamsnap_return_url'] = request.args.get('return_url', '/')

        return redirect(client.get_auth_url(state))

    @app.route('/auth/teamsnap/callback')
    def teamsnap_callback():
        """Handle TeamSnap OAuth callback."""
        # Verify state
        state = request.args.get('state')
        if state != session.pop('teamsnap_state', None):
            return jsonify({'error': 'Invalid state'}), 400

        # Check for errors
        error = request.args.get('error')
        if error:
            return jsonify({'error': error}), 400

        # Exchange code for token
        code = request.args.get('code')
        try:
            token = client.exchange_code(code)

            # Store token in database (associated with current team)
            # This depends on your auth system - adjust as needed
            team_code = session.get('team_code')
            if team_code:
                _store_teamsnap_token(db, team_code, token)

            return_url = session.pop('teamsnap_return_url', '/')
            return redirect(return_url + '?teamsnap=connected')

        except Exception as e:
            logger.error(f"TeamSnap OAuth error: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/teamsnap/teams')
    def teamsnap_teams():
        """Get list of TeamSnap teams."""
        team_code = session.get('team_code')
        if not team_code:
            return jsonify({'error': 'Not authenticated'}), 401

        token = _get_teamsnap_token(db, team_code)
        if not token:
            return jsonify({'error': 'TeamSnap not connected'}), 404

        try:
            teams = client.get_teams(token)
            return jsonify({
                'teams': [
                    {
                        'id': t.id,
                        'name': t.name,
                        'division': t.division_name,
                        'season': t.season_name
                    }
                    for t in teams
                ]
            })
        except Exception as e:
            logger.error(f"Failed to get teams: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/teamsnap/sync/<int:teamsnap_team_id>', methods=['POST'])
    def teamsnap_sync(teamsnap_team_id: int):
        """Sync roster from TeamSnap."""
        team_code = session.get('team_code')
        if not team_code:
            return jsonify({'error': 'Not authenticated'}), 401

        token = _get_teamsnap_token(db, team_code)
        if not token:
            return jsonify({'error': 'TeamSnap not connected'}), 404

        try:
            # Get roster from TeamSnap
            players = client.get_roster(token, teamsnap_team_id)

            # Sync to local database
            synced = _sync_players_to_db(db, team_code, players)

            return jsonify({
                'success': True,
                'synced_count': synced,
                'players': [
                    {
                        'id': p.id,
                        'name': p.full_name,
                        'jersey_number': p.jersey_number,
                        'position': p.position,
                        'is_goalkeeper': p.is_goalkeeper
                    }
                    for p in players
                ]
            })
        except Exception as e:
            logger.error(f"Failed to sync roster: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/auth/teamsnap', methods=['DELETE'])
    def teamsnap_disconnect():
        """Disconnect TeamSnap integration."""
        team_code = session.get('team_code')
        if not team_code:
            return jsonify({'error': 'Not authenticated'}), 401

        _delete_teamsnap_token(db, team_code)
        return jsonify({'success': True})

    @app.route('/api/teamsnap/status')
    def teamsnap_status():
        """Check TeamSnap connection status."""
        return jsonify({
            'configured': client.is_configured,
            'connected': _has_teamsnap_token(db, session.get('team_code'))
        })


# =============================================================================
# Database Helpers (implement based on your DB schema)
# =============================================================================

def _store_teamsnap_token(db, team_code: str, token: TeamSnapToken):
    """Store TeamSnap token in database."""
    # Implementation depends on your database schema
    # Example with SQLAlchemy:
    #
    # from models import TeamSnapConnection
    # conn = TeamSnapConnection.query.filter_by(team_code=team_code).first()
    # if conn:
    #     conn.access_token = token.access_token
    #     conn.refresh_token = token.refresh_token
    #     conn.expires_at = token.expires_at
    #     conn.user_id = token.user_id
    # else:
    #     conn = TeamSnapConnection(
    #         team_code=team_code,
    #         access_token=token.access_token,
    #         refresh_token=token.refresh_token,
    #         expires_at=token.expires_at,
    #         user_id=token.user_id
    #     )
    #     db.session.add(conn)
    # db.session.commit()
    pass


def _get_teamsnap_token(db, team_code: str) -> Optional[TeamSnapToken]:
    """Retrieve TeamSnap token from database."""
    # Implementation depends on your database schema
    return None


def _has_teamsnap_token(db, team_code: str) -> bool:
    """Check if team has TeamSnap connection."""
    return _get_teamsnap_token(db, team_code) is not None


def _delete_teamsnap_token(db, team_code: str):
    """Delete TeamSnap connection."""
    pass


def _sync_players_to_db(db, team_code: str, players: List[TeamSnapPlayer]) -> int:
    """
    Sync TeamSnap players to local player database.

    Updates existing players by jersey number, creates new ones.
    Returns count of synced players.
    """
    # Implementation depends on your database schema
    # Example:
    #
    # from models import Player
    # synced = 0
    # for ts_player in players:
    #     player = Player.query.filter_by(
    #         team_code=team_code,
    #         jersey_number=ts_player.jersey_number
    #     ).first()
    #
    #     if player:
    #         player.first_name = ts_player.first_name
    #         player.last_name = ts_player.last_name
    #         player.position = ts_player.position
    #     else:
    #         player = Player(
    #             team_code=team_code,
    #             first_name=ts_player.first_name,
    #             last_name=ts_player.last_name,
    #             jersey_number=ts_player.jersey_number,
    #             position=ts_player.position
    #         )
    #         db.session.add(player)
    #     synced += 1
    #
    # db.session.commit()
    # return synced
    return len(players)
