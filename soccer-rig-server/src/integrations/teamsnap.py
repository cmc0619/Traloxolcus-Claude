"""
TeamSnap Integration for Soccer Rig

Provides OAuth2 authentication and roster synchronization with TeamSnap.
Uses the TeamSnap API v3 to pull team rosters, player info, and parent contacts.

Features:
- Any parent can connect their TeamSnap account
- Auto-creates teams when new ones are discovered
- Links players to parents automatically
- Syncs jersey numbers per-team (kid can have different # on different teams)
- Pulls parent emails for notifications

OAuth Flow:
1. User clicks "Connect TeamSnap" -> redirected to TeamSnap auth
2. TeamSnap redirects back with authorization code
3. We exchange code for access token
4. Store token and sync all teams/rosters

API Reference: https://www.teamsnap.com/documentation/apiv3
"""

import os
import requests
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlencode
import logging
import secrets

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
    birthday: Optional[str] = None  # For birth year

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def birth_year(self) -> Optional[int]:
        """Extract birth year from birthday string."""
        if self.birthday:
            try:
                return int(self.birthday[:4])
            except:
                pass
        return None


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
        """Generate TeamSnap OAuth authorization URL."""
        params = {
            'response_type': 'code',
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri,
            'scope': 'read',
            'state': state
        }
        return f"{TEAMSNAP_AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> TeamSnapToken:
        """Exchange authorization code for access token."""
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
        """Refresh an expired access token."""
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
        """Get all teams the user has access to."""
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
        """Get full roster for a team including contact info."""
        if token.is_expired:
            token = self.refresh_token(token)

        members_data = self._api_request(
            token.access_token,
            '/members',
            params={'team_id': team_id}
        )

        players = []
        for item in members_data.get('collection', {}).get('items', []):
            member = {d['name']: d['value'] for d in item['data']}

            # Skip non-players (coaches, managers)
            if member.get('is_non_player', False):
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
                phone_numbers=contacts.get('phones', []),
                birthday=member.get('birthday')
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


# =============================================================================
# Database Sync Service
# =============================================================================

class TeamSnapSyncService:
    """
    Syncs TeamSnap data to local database.

    - Auto-creates teams when new ones are discovered
    - Links players to teams with per-team jersey numbers
    - Links parents to their children
    - Updates existing records rather than duplicating
    """

    def __init__(self, db_session, client: Optional[TeamSnapClient] = None):
        self.db = db_session
        self.client = client or TeamSnapClient()

    def sync_user_teams(self, user_id: int) -> Dict:
        """
        Sync all teams for a user from TeamSnap.

        Returns summary of synced data.
        """
        from ..models import User, Team, Player, Organization

        user = self.db.query(User).get(user_id)
        if not user or not user.teamsnap_token:
            return {'error': 'User not connected to TeamSnap'}

        token = TeamSnapToken.from_dict(eval(user.teamsnap_token))  # TODO: proper encryption

        try:
            ts_teams = self.client.get_teams(token)
        except Exception as e:
            logger.error(f"Failed to fetch teams: {e}")
            return {'error': str(e)}

        synced = {
            'teams_created': 0,
            'teams_updated': 0,
            'players_created': 0,
            'players_updated': 0,
            'teams': []
        }

        for ts_team in ts_teams:
            result = self._sync_team(user, token, ts_team)
            synced['teams'].append(result)
            if result.get('created'):
                synced['teams_created'] += 1
            else:
                synced['teams_updated'] += 1
            synced['players_created'] += result.get('players_created', 0)
            synced['players_updated'] += result.get('players_updated', 0)

        return synced

    def _sync_team(self, user, token: TeamSnapToken, ts_team: TeamSnapTeam) -> Dict:
        """Sync a single team and its roster."""
        from ..models import Team, Player, Organization, team_player, parent_player
        from sqlalchemy import and_

        # Find or create team
        team = self.db.query(Team).filter(
            Team.teamsnap_team_id == ts_team.id
        ).first()

        created = False
        if not team:
            # Auto-generate team code
            team_code = self._generate_team_code(ts_team.name)

            team = Team(
                name=ts_team.name,
                team_code=team_code,
                season=ts_team.season_name,
                teamsnap_team_id=ts_team.id
            )
            self.db.add(team)
            self.db.flush()
            created = True
            logger.info(f"Created team: {ts_team.name} (code: {team_code})")
        else:
            # Update team info
            team.name = ts_team.name
            team.season = ts_team.season_name

        team.teamsnap_last_sync = datetime.utcnow()

        # Sync roster
        ts_players = self.client.get_roster(token, ts_team.id)
        players_created = 0
        players_updated = 0

        for ts_player in ts_players:
            player_result = self._sync_player(user, team, ts_player)
            if player_result.get('created'):
                players_created += 1
            else:
                players_updated += 1

        self.db.commit()

        return {
            'team_id': team.id,
            'name': team.name,
            'team_code': team.team_code,
            'created': created,
            'players_created': players_created,
            'players_updated': players_updated
        }

    def _sync_player(self, user, team, ts_player: TeamSnapPlayer) -> Dict:
        """Sync a player and link to team with jersey number."""
        from ..models import Player, team_player, parent_player, PlayerPosition
        from sqlalchemy import and_, insert, update

        # Find player by TeamSnap ID first, then by name+birth year
        player = self.db.query(Player).filter(
            Player.teamsnap_member_id == ts_player.id
        ).first()

        created = False
        if not player and ts_player.birth_year:
            # Try to find by name and birth year (might be from another team)
            player = self.db.query(Player).filter(
                and_(
                    Player.first_name == ts_player.first_name,
                    Player.last_name == ts_player.last_name,
                    Player.birth_year == ts_player.birth_year
                )
            ).first()

        if not player:
            # Create new player
            position = PlayerPosition.GOALKEEPER if ts_player.is_goalkeeper else PlayerPosition.UNKNOWN
            if ts_player.position:
                pos_lower = ts_player.position.lower()
                if 'forward' in pos_lower or 'striker' in pos_lower:
                    position = PlayerPosition.FORWARD
                elif 'mid' in pos_lower:
                    position = PlayerPosition.MIDFIELDER
                elif 'defend' in pos_lower or 'back' in pos_lower:
                    position = PlayerPosition.DEFENDER

            player = Player(
                first_name=ts_player.first_name,
                last_name=ts_player.last_name,
                birth_year=ts_player.birth_year or 2010,  # Default if unknown
                default_position=position,
                teamsnap_member_id=ts_player.id
            )
            self.db.add(player)
            self.db.flush()
            created = True
            logger.info(f"Created player: {ts_player.full_name}")
        else:
            # Update TeamSnap ID if not set
            if not player.teamsnap_member_id:
                player.teamsnap_member_id = ts_player.id

        # Link player to team with jersey number (per-team)
        existing_link = self.db.execute(
            team_player.select().where(
                and_(
                    team_player.c.team_id == team.id,
                    team_player.c.player_id == player.id
                )
            )
        ).first()

        if not existing_link:
            self.db.execute(
                team_player.insert().values(
                    team_id=team.id,
                    player_id=player.id,
                    jersey_number=ts_player.jersey_number,
                    position=ts_player.position,
                    is_active=True
                )
            )
        else:
            # Update jersey number if changed
            self.db.execute(
                team_player.update().where(
                    and_(
                        team_player.c.team_id == team.id,
                        team_player.c.player_id == player.id
                    )
                ).values(
                    jersey_number=ts_player.jersey_number,
                    position=ts_player.position
                )
            )

        # Link parent to player if emails match
        if ts_player.email_addresses and user.email in ts_player.email_addresses:
            existing_parent_link = self.db.execute(
                parent_player.select().where(
                    and_(
                        parent_player.c.parent_id == user.id,
                        parent_player.c.player_id == player.id
                    )
                )
            ).first()

            if not existing_parent_link:
                self.db.execute(
                    parent_player.insert().values(
                        parent_id=user.id,
                        player_id=player.id,
                        relationship='parent'
                    )
                )
                logger.info(f"Linked {user.email} as parent of {player.full_name}")

        return {'created': created, 'player_id': player.id}

    def _generate_team_code(self, team_name: str) -> str:
        """Generate unique team code from name."""
        from ..models import Team

        # Create base code from team name
        base = ''.join(c for c in team_name.upper() if c.isalnum())[:6]
        if len(base) < 4:
            base = base + secrets.token_hex(2).upper()

        code = base
        suffix = 1

        # Ensure unique
        while self.db.query(Team).filter(Team.team_code == code).first():
            code = f"{base}{suffix}"
            suffix += 1

        return code


# =============================================================================
# Flask Routes
# =============================================================================

def register_teamsnap_routes(app, db):
    """
    Register TeamSnap OAuth routes with Flask app.

    Any logged-in user (parent) can connect their TeamSnap account.
    When connected, all their teams are synced automatically.
    """
    from flask import redirect, request, session, jsonify, g

    client = TeamSnapClient()

    @app.route('/auth/teamsnap')
    def teamsnap_auth():
        """Start TeamSnap OAuth flow - any logged-in user can connect."""
        if not client.is_configured:
            return jsonify({'error': 'TeamSnap not configured'}), 503

        if 'user_id' not in session:
            return jsonify({'error': 'Please log in first'}), 401

        # Generate state for CSRF protection
        state = secrets.token_urlsafe(32)
        session['teamsnap_state'] = state
        session['teamsnap_return_url'] = request.args.get('return_url', '/')

        return redirect(client.get_auth_url(state))

    @app.route('/auth/teamsnap/callback')
    def teamsnap_callback():
        """Handle TeamSnap OAuth callback and sync all teams."""
        from ..models import User

        # Verify state
        state = request.args.get('state')
        if state != session.pop('teamsnap_state', None):
            return jsonify({'error': 'Invalid state'}), 400

        error = request.args.get('error')
        if error:
            return jsonify({'error': error}), 400

        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Session expired'}), 401

        # Exchange code for token
        code = request.args.get('code')
        try:
            token = client.exchange_code(code)

            # Store token on user
            user = db.query(User).get(user_id)
            user.teamsnap_token = str(token.to_dict())
            user.teamsnap_user_id = token.user_id
            db.commit()

            # Auto-sync all teams
            sync_service = TeamSnapSyncService(db, client)
            sync_result = sync_service.sync_user_teams(user_id)

            logger.info(f"TeamSnap sync for user {user_id}: {sync_result}")

            return_url = session.pop('teamsnap_return_url', '/')
            return redirect(f"{return_url}?teamsnap=connected&teams={sync_result.get('teams_created', 0)}")

        except Exception as e:
            logger.error(f"TeamSnap OAuth error: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/teamsnap/sync', methods=['POST'])
    def teamsnap_sync_all():
        """Manually trigger sync of all teams."""
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401

        sync_service = TeamSnapSyncService(db, client)
        result = sync_service.sync_user_teams(user_id)

        return jsonify(result)

    @app.route('/api/teamsnap/teams')
    def teamsnap_teams():
        """Get list of synced teams for current user."""
        from ..models import User, Team

        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401

        user = db.query(User).get(user_id)

        # Get teams where user is coach OR has children
        teams = set()

        # Teams user coaches
        for team in user.coached_teams:
            teams.add(team)

        # Teams with user's children
        for child in user.children:
            for team in child.teams:
                teams.add(team)

        return jsonify({
            'connected': bool(user.teamsnap_token),
            'teams': [
                {
                    'id': t.id,
                    'name': t.name,
                    'team_code': t.team_code,
                    'season': t.season,
                    'last_sync': t.teamsnap_last_sync.isoformat() if t.teamsnap_last_sync else None
                }
                for t in teams
            ]
        })

    @app.route('/api/teamsnap/children')
    def teamsnap_children():
        """Get all children linked to current user."""
        from ..models import User

        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401

        user = db.query(User).get(user_id)

        return jsonify({
            'children': [
                {
                    'id': child.id,
                    'name': child.full_name,
                    'birth_year': child.birth_year,
                    'teams': [
                        {'id': t.id, 'name': t.name}
                        for t in child.teams
                    ]
                }
                for child in user.children
            ]
        })

    @app.route('/auth/teamsnap', methods=['DELETE'])
    def teamsnap_disconnect():
        """Disconnect TeamSnap integration."""
        from ..models import User

        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401

        user = db.query(User).get(user_id)
        user.teamsnap_token = None
        user.teamsnap_user_id = None
        db.commit()

        return jsonify({'success': True})

    @app.route('/api/teamsnap/status')
    def teamsnap_status():
        """Check TeamSnap connection status."""
        from ..models import User

        user_id = session.get('user_id')
        user = db.query(User).get(user_id) if user_id else None

        return jsonify({
            'configured': client.is_configured,
            'connected': bool(user and user.teamsnap_token),
            'user_id': user.teamsnap_user_id if user else None
        })
