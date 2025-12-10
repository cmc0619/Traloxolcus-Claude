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
    sport_id: int  # 2 = Soccer
    division_name: Optional[str] = None
    season_name: Optional[str] = None
    league_name: Optional[str] = None
    time_zone: Optional[str] = None
    raw_data: Optional[Dict] = None  # Store full API response for JSONB
    players: List[TeamSnapPlayer] = field(default_factory=list)

    @property
    def is_soccer(self) -> bool:
        return self.sport_id == 2


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

    def get_teams(self, token: TeamSnapToken, soccer_only: bool = True) -> List[TeamSnapTeam]:
        """
        Get all teams the user has access to.

        Args:
            token: OAuth token
            soccer_only: If True, only return soccer teams (sport_id=2)

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

            sport_id = team_data.get('sport_id', 0)

            # Filter to soccer only (sport_id = 2)
            if soccer_only and sport_id != 2:
                logger.debug(f"Skipping non-soccer team: {team_data.get('name')} (sport_id={sport_id})")
                continue

            teams.append(TeamSnapTeam(
                id=team_data['id'],
                name=team_data['name'],
                sport_id=sport_id,
                division_name=team_data.get('division_name'),
                season_name=team_data.get('season_name'),
                league_name=team_data.get('league_name'),
                time_zone=team_data.get('time_zone_iana_name'),
                raw_data=team_data  # Store full response for JSONB
            ))

        logger.info(f"Found {len(teams)} soccer teams (filtered from API response)")
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

        token = TeamSnapToken.from_dict(user.teamsnap_token)  # JSONB stores dict natively

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
                teamsnap_team_id=ts_team.id,
                teamsnap_data=ts_team.raw_data  # Store full API response in JSONB
            )
            self.db.add(team)
            self.db.flush()
            created = True
            logger.info(f"Created team: {ts_team.name} (code: {team_code})")
        else:
            # Update team info
            team.name = ts_team.name
            team.season = ts_team.season_name
            team.teamsnap_data = ts_team.raw_data  # Update JSONB on sync

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
            user.teamsnap_token = token.to_dict()  # JSONB stores dict natively
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

    # -------------------------------------------------------------------------
    # Data Explorer API - Browse imported TeamSnap data
    # -------------------------------------------------------------------------

    @app.route('/api/data/teams')
    def api_data_teams():
        """Get all teams in the system (for dropdowns)."""
        from ..models import Team

        teams = db.query(Team).filter(Team.is_active == True).all()

        return jsonify({
            'teams': [
                {
                    'id': t.id,
                    'name': t.name,
                    'team_code': t.team_code,
                    'season': t.season,
                    'birth_year_start': t.birth_year_start,
                    'player_count': len(t.players),
                    'from_teamsnap': t.teamsnap_team_id is not None
                }
                for t in teams
            ]
        })

    @app.route('/api/data/players')
    def api_data_players():
        """Get all players (for dropdowns and linking)."""
        from ..models import Player

        team_id = request.args.get('team_id', type=int)

        query = db.query(Player)
        if team_id:
            from ..models import team_player
            query = query.join(team_player).filter(team_player.c.team_id == team_id)

        players = query.order_by(Player.last_name, Player.first_name).all()

        return jsonify({
            'players': [
                {
                    'id': p.id,
                    'name': p.full_name,
                    'first_name': p.first_name,
                    'last_name': p.last_name,
                    'birth_year': p.birth_year,
                    'position': p.default_position.value if p.default_position else None,
                    'teams': [{'id': t.id, 'name': t.name} for t in p.teams],
                    'from_teamsnap': p.teamsnap_member_id is not None
                }
                for p in players
            ]
        })

    @app.route('/api/data/explorer')
    def api_data_explorer():
        """Full data explorer - all TeamSnap imported data."""
        from ..models import Team, Player, Organization, User

        # Get all data with TeamSnap links
        teams = db.query(Team).filter(Team.teamsnap_team_id.isnot(None)).all()
        players = db.query(Player).filter(Player.teamsnap_member_id.isnot(None)).all()
        users_with_ts = db.query(User).filter(User.teamsnap_user_id.isnot(None)).all()

        return jsonify({
            'summary': {
                'teams_from_teamsnap': len(teams),
                'players_from_teamsnap': len(players),
                'users_connected': len(users_with_ts)
            },
            'teams': [
                {
                    'id': t.id,
                    'name': t.name,
                    'team_code': t.team_code,
                    'season': t.season,
                    'teamsnap_id': t.teamsnap_team_id,
                    'last_sync': t.teamsnap_last_sync.isoformat() if t.teamsnap_last_sync else None,
                    'players': [
                        {
                            'id': p.id,
                            'name': p.full_name,
                            'birth_year': p.birth_year,
                            'teamsnap_id': p.teamsnap_member_id
                        }
                        for p in t.players
                    ]
                }
                for t in teams
            ],
            'unlinked_players': [
                {
                    'id': p.id,
                    'name': p.full_name,
                    'birth_year': p.birth_year,
                    'teamsnap_id': p.teamsnap_member_id,
                    'teams': [t.name for t in p.teams],
                    'has_parents': len(p.parents) > 0
                }
                for p in players
                if len(p.parents) == 0
            ]
        })

    @app.route('/api/data/link-player', methods=['POST'])
    def api_link_player():
        """Link a user to a player (for parents/family to claim children)."""
        from ..models import User, Player, parent_player
        from sqlalchemy import and_

        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401

        data = request.get_json()
        player_id = data.get('player_id')
        relationship = data.get('relationship', 'parent')

        if not player_id:
            return jsonify({'error': 'player_id required'}), 400

        player = db.query(Player).get(player_id)
        if not player:
            return jsonify({'error': 'Player not found'}), 404

        # Check if already linked
        existing = db.execute(
            parent_player.select().where(
                and_(
                    parent_player.c.parent_id == user_id,
                    parent_player.c.player_id == player_id
                )
            )
        ).first()

        if existing:
            return jsonify({'error': 'Already linked'}), 400

        # Create link
        db.execute(
            parent_player.insert().values(
                parent_id=user_id,
                player_id=player_id,
                relationship=relationship
            )
        )
        db.commit()

        return jsonify({
            'success': True,
            'message': f'Linked to {player.full_name}'
        })

    @app.route('/api/data/create-player', methods=['POST'])
    def api_create_player():
        """Create a new player (when not from TeamSnap)."""
        from ..models import Player, Team, PlayerPosition, team_player, parent_player

        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401

        data = request.get_json()

        # Validate required fields
        if not data.get('first_name') or not data.get('last_name'):
            return jsonify({'error': 'first_name and last_name required'}), 400
        if not data.get('birth_year'):
            return jsonify({'error': 'birth_year required'}), 400

        # Map position
        position = PlayerPosition.UNKNOWN
        if data.get('position'):
            try:
                position = PlayerPosition(data['position'])
            except ValueError:
                pass

        # Create player
        player = Player(
            first_name=data['first_name'],
            last_name=data['last_name'],
            birth_year=data['birth_year'],
            default_position=position
        )
        db.add(player)
        db.flush()

        # Link to team if provided
        if data.get('team_id'):
            team = db.query(Team).get(data['team_id'])
            if team:
                db.execute(
                    team_player.insert().values(
                        team_id=team.id,
                        player_id=player.id,
                        jersey_number=data.get('jersey_number'),
                        is_active=True
                    )
                )

        # Auto-link to creating user if they want
        if data.get('link_to_me'):
            db.execute(
                parent_player.insert().values(
                    parent_id=user_id,
                    player_id=player.id,
                    relationship=data.get('relationship', 'parent')
                )
            )

        db.commit()

        return jsonify({
            'success': True,
            'player': {
                'id': player.id,
                'name': player.full_name
            }
        })

    # -------------------------------------------------------------------------
    # Data Explorer UI
    # -------------------------------------------------------------------------

    @app.route('/data-explorer')
    def data_explorer_page():
        """TeamSnap data explorer page."""
        from flask import render_template_string

        return render_template_string(DATA_EXPLORER_HTML)

    # -------------------------------------------------------------------------
    # Advanced JSONB Query API - PostgreSQL-specific features
    # -------------------------------------------------------------------------

    @app.route('/api/data/query/teams-by-league')
    def api_teams_by_league():
        """
        Query teams by league using JSONB containment.

        PostgreSQL JSONB feature: @> operator for containment
        Example: teamsnap_data @> '{"league_name": "Cherry Hill Soccer Club"}'
        """
        from ..models import Team
        from sqlalchemy import text

        league = request.args.get('league')
        if not league:
            return jsonify({'error': 'league parameter required'}), 400

        # Use JSONB containment operator @>
        teams = db.query(Team).filter(
            Team.teamsnap_data['league_name'].astext == league
        ).all()

        return jsonify({
            'query': f"league_name = {league}",
            'count': len(teams),
            'teams': [
                {
                    'id': t.id,
                    'name': t.name,
                    'league': t.teamsnap_data.get('league_name') if t.teamsnap_data else None,
                    'division': t.teamsnap_data.get('division_name') if t.teamsnap_data else None
                }
                for t in teams
            ]
        })

    @app.route('/api/data/query/teams-by-division')
    def api_teams_by_division():
        """
        Query teams by division pattern using JSONB text search.

        PostgreSQL JSONB feature: ->> extracts as text for LIKE/ILIKE
        """
        from ..models import Team

        pattern = request.args.get('pattern', '')

        # Use JSONB ->> to extract text, then ILIKE for pattern match
        teams = db.query(Team).filter(
            Team.teamsnap_data['division_name'].astext.ilike(f'%{pattern}%')
        ).all()

        return jsonify({
            'query': f"division_name ILIKE '%{pattern}%'",
            'count': len(teams),
            'teams': [
                {
                    'id': t.id,
                    'name': t.name,
                    'division': t.teamsnap_data.get('division_name') if t.teamsnap_data else None
                }
                for t in teams
            ]
        })

    @app.route('/api/data/query/teams-stats')
    def api_teams_jsonb_stats():
        """
        Aggregate stats from JSONB data using PostgreSQL functions.

        PostgreSQL JSONB features:
        - jsonb_object_keys() - get all keys
        - jsonb_array_length() - count array items
        - Casting with ::int for numeric operations
        """
        from ..models import Team
        from sqlalchemy import func, text

        # Get all teams with JSONB data
        teams = db.query(Team).filter(Team.teamsnap_data.isnot(None)).all()

        # Aggregate by league using Python (could also use SQL GROUP BY)
        leagues = {}
        divisions = {}
        timezones = {}

        for team in teams:
            data = team.teamsnap_data or {}

            league = data.get('league_name', 'Unknown')
            leagues[league] = leagues.get(league, 0) + 1

            division = data.get('division_name', 'Unknown')
            divisions[division] = divisions.get(division, 0) + 1

            tz = data.get('time_zone_iana_name', 'Unknown')
            timezones[tz] = timezones.get(tz, 0) + 1

        return jsonify({
            'total_teams': len(teams),
            'by_league': dict(sorted(leagues.items(), key=lambda x: -x[1])),
            'by_division': dict(sorted(divisions.items(), key=lambda x: -x[1])),
            'by_timezone': dict(sorted(timezones.items(), key=lambda x: -x[1]))
        })

    @app.route('/api/data/query/raw-jsonb')
    def api_raw_jsonb_query():
        """
        Execute a raw JSONB path query.

        PostgreSQL JSONB features:
        - ? operator: key exists
        - ?| operator: any key exists
        - ?& operator: all keys exist
        - #> operator: path extraction
        - @> operator: containment

        Example: /api/data/query/raw-jsonb?path=league_name
        """
        from ..models import Team
        from sqlalchemy import text

        path = request.args.get('path')
        value = request.args.get('value')

        if not path:
            return jsonify({
                'error': 'path parameter required',
                'examples': [
                    '/api/data/query/raw-jsonb?path=league_name',
                    '/api/data/query/raw-jsonb?path=league_name&value=Cherry Hill',
                    '/api/data/query/raw-jsonb?path=is_retired&value=false'
                ]
            }), 400

        # Build query based on parameters
        if value:
            # Filter by path = value
            teams = db.query(Team).filter(
                Team.teamsnap_data[path].astext == value
            ).all()
        else:
            # Just extract the path values
            teams = db.query(Team).filter(
                Team.teamsnap_data.isnot(None)
            ).all()

        # Extract requested field from each team
        results = []
        for t in teams:
            if t.teamsnap_data:
                results.append({
                    'team_id': t.id,
                    'team_name': t.name,
                    path: t.teamsnap_data.get(path)
                })

        return jsonify({
            'query': f"teamsnap_data->>'{path}'" + (f" = '{value}'" if value else ''),
            'count': len(results),
            'results': results
        })

    @app.route('/api/data/query/teams-with-field')
    def api_teams_with_field():
        """
        Find teams where a specific JSONB field exists.

        PostgreSQL JSONB feature: ? operator for key existence
        """
        from ..models import Team
        from sqlalchemy import text

        field = request.args.get('field', 'league_name')

        # Use ? operator for key existence check
        teams = db.query(Team).filter(
            text(f"teamsnap_data ? :field")
        ).params(field=field).all()

        return jsonify({
            'query': f"teamsnap_data ? '{field}'",
            'count': len(teams),
            'teams': [{'id': t.id, 'name': t.name} for t in teams]
        })


# =============================================================================
# Data Explorer HTML Template
# =============================================================================

DATA_EXPLORER_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Data Explorer - Soccer Rig</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f0f4f8; color: #1a202c; min-height: 100vh; }
        .header { background: linear-gradient(135deg, #1a472a 0%, #2d5a27 100%); color: white; padding: 1.5rem 2rem; }
        .header-content { max-width: 1200px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; }
        .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
        .summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2rem; }
        .summary-card { background: white; padding: 1.5rem; border-radius: 0.75rem; text-align: center; }
        .summary-value { font-size: 2.5rem; font-weight: 700; color: #10b981; }
        .summary-label { color: #64748b; font-size: 0.875rem; }
        .card { background: white; border-radius: 1rem; padding: 1.5rem; margin-bottom: 1.5rem; }
        .card h2 { font-size: 1.25rem; margin-bottom: 1rem; display: flex; align-items: center; gap: 0.5rem; }
        .badge { background: #e2e8f0; color: #64748b; padding: 0.25rem 0.5rem; border-radius: 1rem; font-size: 0.75rem; }
        .badge.ts { background: #dbeafe; color: #1d4ed8; }
        .team-card { background: #f8fafc; border-radius: 0.5rem; padding: 1rem; margin-bottom: 0.75rem; }
        .team-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }
        .team-name { font-weight: 600; }
        .team-meta { color: #64748b; font-size: 0.875rem; }
        .player-list { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.75rem; }
        .player-chip { background: #e2e8f0; padding: 0.25rem 0.75rem; border-radius: 1rem; font-size: 0.875rem; }
        .player-chip.unlinked { background: #fef3c7; color: #92400e; }
        .actions { display: flex; gap: 0.5rem; margin-top: 1rem; }
        .btn { padding: 0.5rem 1rem; border-radius: 0.5rem; border: none; cursor: pointer; font-weight: 500; }
        .btn-primary { background: #10b981; color: white; }
        .btn-secondary { background: #e2e8f0; color: #374151; }
        .modal { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); align-items: center; justify-content: center; z-index: 100; }
        .modal.active { display: flex; }
        .modal-content { background: white; padding: 2rem; border-radius: 1rem; width: 100%; max-width: 500px; max-height: 90vh; overflow-y: auto; }
        .modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem; }
        .modal-close { background: none; border: none; font-size: 1.5rem; cursor: pointer; color: #64748b; }
        .form-group { margin-bottom: 1rem; }
        .form-group label { display: block; margin-bottom: 0.5rem; font-weight: 500; }
        .form-group input, .form-group select { width: 100%; padding: 0.75rem; border: 2px solid #e2e8f0; border-radius: 0.5rem; }
        .form-group input:focus, .form-group select:focus { outline: none; border-color: #10b981; }
        .checkbox-group { display: flex; align-items: center; gap: 0.5rem; }
        .checkbox-group input { width: auto; }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-content">
            <h1>Data Explorer</h1>
            <a href="/dashboard" style="color: white; text-decoration: none;">Back to Dashboard</a>
        </div>
    </div>
    <div class="container">
        <div class="summary-grid" id="summary">
            <div class="summary-card">
                <div class="summary-value" id="team-count">-</div>
                <div class="summary-label">Teams</div>
            </div>
            <div class="summary-card">
                <div class="summary-value" id="player-count">-</div>
                <div class="summary-label">Players</div>
            </div>
            <div class="summary-card">
                <div class="summary-value" id="connected-count">-</div>
                <div class="summary-label">Users Connected</div>
            </div>
            <div class="summary-card">
                <div class="summary-value" id="unlinked-count">-</div>
                <div class="summary-label">Unlinked Players</div>
            </div>
        </div>

        <div class="actions">
            <button class="btn btn-primary" onclick="showAddPlayerModal()">+ Add Player</button>
            <button class="btn btn-secondary" onclick="syncTeamSnap()">Sync TeamSnap</button>
            <button class="btn btn-secondary" onclick="loadData()">Refresh</button>
        </div>

        <div class="card">
            <h2>Teams <span class="badge ts">from TeamSnap</span></h2>
            <div id="teams-list">Loading...</div>
        </div>

        <div class="card">
            <h2>Unlinked Players <span class="badge">need parent link</span></h2>
            <div id="unlinked-list">Loading...</div>
        </div>
    </div>

    <!-- Add Player Modal -->
    <div class="modal" id="add-player-modal">
        <div class="modal-content">
            <div class="modal-header">
                <h2>Add Player</h2>
                <button class="modal-close" onclick="hideModal('add-player-modal')">&times;</button>
            </div>
            <form id="add-player-form" onsubmit="createPlayer(event)">
                <div class="form-group">
                    <label>First Name</label>
                    <input type="text" name="first_name" required>
                </div>
                <div class="form-group">
                    <label>Last Name</label>
                    <input type="text" name="last_name" required>
                </div>
                <div class="form-group">
                    <label>Birth Year</label>
                    <input type="number" name="birth_year" min="2000" max="2020" required>
                </div>
                <div class="form-group">
                    <label>Position</label>
                    <select name="position">
                        <option value="unknown">Unknown</option>
                        <option value="goalkeeper">Goalkeeper</option>
                        <option value="defender">Defender</option>
                        <option value="midfielder">Midfielder</option>
                        <option value="forward">Forward</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Team</label>
                    <select name="team_id" id="team-select">
                        <option value="">No Team</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Jersey Number</label>
                    <input type="text" name="jersey_number" placeholder="Optional">
                </div>
                <div class="form-group checkbox-group">
                    <input type="checkbox" name="link_to_me" id="link-to-me" checked>
                    <label for="link-to-me">Link this player to my account</label>
                </div>
                <button type="submit" class="btn btn-primary" style="width: 100%;">Create Player</button>
            </form>
        </div>
    </div>

    <!-- Link Player Modal -->
    <div class="modal" id="link-player-modal">
        <div class="modal-content">
            <div class="modal-header">
                <h2>Link Player</h2>
                <button class="modal-close" onclick="hideModal('link-player-modal')">&times;</button>
            </div>
            <p id="link-player-name" style="margin-bottom: 1rem; font-weight: 600;"></p>
            <div class="form-group">
                <label>Relationship</label>
                <select id="link-relationship">
                    <option value="parent">Parent</option>
                    <option value="guardian">Guardian</option>
                    <option value="grandparent">Grandparent</option>
                    <option value="family">Family Member</option>
                </select>
            </div>
            <button class="btn btn-primary" style="width: 100%;" onclick="linkPlayer()">Link to My Account</button>
        </div>
    </div>

    <script>
        let currentLinkPlayerId = null;

        async function loadData() {
            try {
                const response = await fetch('/api/data/explorer');
                const data = await response.json();

                // Update summary
                document.getElementById('team-count').textContent = data.summary.teams_from_teamsnap;
                document.getElementById('player-count').textContent = data.summary.players_from_teamsnap;
                document.getElementById('connected-count').textContent = data.summary.users_connected;
                document.getElementById('unlinked-count').textContent = data.unlinked_players.length;

                // Render teams
                const teamsList = document.getElementById('teams-list');
                if (data.teams.length === 0) {
                    teamsList.innerHTML = '<p style="color: #64748b;">No teams imported yet. Connect TeamSnap to sync teams.</p>';
                } else {
                    teamsList.innerHTML = data.teams.map(team => `
                        <div class="team-card">
                            <div class="team-header">
                                <div>
                                    <div class="team-name">${team.name}</div>
                                    <div class="team-meta">Code: ${team.team_code} | Season: ${team.season || 'N/A'}</div>
                                </div>
                                <span class="badge">${team.players.length} players</span>
                            </div>
                            <div class="player-list">
                                ${team.players.map(p => `<span class="player-chip">${p.name} (${p.birth_year})</span>`).join('')}
                            </div>
                        </div>
                    `).join('');
                }

                // Render unlinked players
                const unlinkedList = document.getElementById('unlinked-list');
                if (data.unlinked_players.length === 0) {
                    unlinkedList.innerHTML = '<p style="color: #64748b;">All players are linked to parent accounts.</p>';
                } else {
                    unlinkedList.innerHTML = `
                        <div class="player-list">
                            ${data.unlinked_players.map(p => `
                                <span class="player-chip unlinked" style="cursor: pointer;" onclick="showLinkModal(${p.id}, '${p.name}')">
                                    ${p.name} (${p.birth_year}) - ${p.teams.join(', ') || 'No team'}
                                </span>
                            `).join('')}
                        </div>
                    `;
                }

                // Load teams for dropdown
                loadTeamsDropdown();

            } catch (error) {
                console.error('Failed to load data:', error);
            }
        }

        async function loadTeamsDropdown() {
            const response = await fetch('/api/data/teams');
            const data = await response.json();

            const select = document.getElementById('team-select');
            select.innerHTML = '<option value="">No Team</option>' +
                data.teams.map(t => `<option value="${t.id}">${t.name}</option>`).join('');
        }

        async function syncTeamSnap() {
            try {
                const response = await fetch('/api/teamsnap/sync', { method: 'POST' });
                const result = await response.json();
                if (result.error) {
                    alert('Sync failed: ' + result.error);
                } else {
                    alert(`Synced! Created ${result.teams_created} teams, ${result.players_created} players`);
                    loadData();
                }
            } catch (error) {
                alert('Sync failed: ' + error.message);
            }
        }

        function showAddPlayerModal() {
            document.getElementById('add-player-modal').classList.add('active');
        }

        function showLinkModal(playerId, playerName) {
            currentLinkPlayerId = playerId;
            document.getElementById('link-player-name').textContent = playerName;
            document.getElementById('link-player-modal').classList.add('active');
        }

        function hideModal(id) {
            document.getElementById(id).classList.remove('active');
        }

        async function createPlayer(event) {
            event.preventDefault();
            const form = event.target;
            const data = {
                first_name: form.first_name.value,
                last_name: form.last_name.value,
                birth_year: parseInt(form.birth_year.value),
                position: form.position.value,
                team_id: form.team_id.value ? parseInt(form.team_id.value) : null,
                jersey_number: form.jersey_number.value || null,
                link_to_me: form.link_to_me.checked
            };

            try {
                const response = await fetch('/api/data/create-player', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                const result = await response.json();
                if (result.success) {
                    alert('Player created: ' + result.player.name);
                    hideModal('add-player-modal');
                    form.reset();
                    loadData();
                } else {
                    alert('Failed: ' + result.error);
                }
            } catch (error) {
                alert('Failed: ' + error.message);
            }
        }

        async function linkPlayer() {
            const relationship = document.getElementById('link-relationship').value;

            try {
                const response = await fetch('/api/data/link-player', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ player_id: currentLinkPlayerId, relationship })
                });
                const result = await response.json();
                if (result.success) {
                    alert(result.message);
                    hideModal('link-player-modal');
                    loadData();
                } else {
                    alert('Failed: ' + result.error);
                }
            } catch (error) {
                alert('Failed: ' + error.message);
            }
        }

        // Initial load
        loadData();
    </script>
</body>
</html>
"""
