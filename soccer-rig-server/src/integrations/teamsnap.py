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
            except (ValueError, IndexError, TypeError):
                logger.debug(f"Failed to parse birth year from: {self.birthday}")
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
class TeamSnapGame:
    """
    Game/Event information from TeamSnap.

    Per TEAMSNAP_SCHEMA.md, Event fields:
    - id, team_id, is_game (distinguishes games from practices)
    - game_type ("Home" or "Away")
    - start_date, opponent_name, location_name
    - points_for_team, points_for_opponent (scores)
    - is_canceled, formatted_title
    """
    id: int
    team_id: int
    is_game: bool  # True = game, False = practice/event
    game_type: str  # "Home" or "Away"
    start_date: Optional[datetime] = None
    opponent_name: Optional[str] = None
    location_name: Optional[str] = None
    location_details: Optional[str] = None  # additional_location_details
    points_for_team: Optional[int] = None
    points_for_opponent: Optional[int] = None
    formatted_title: Optional[str] = None
    is_canceled: bool = False
    uniform: Optional[str] = None
    raw_data: Optional[Dict] = None  # Store full API response for JSONB

    @property
    def is_home(self) -> bool:
        return self.game_type == "Home"

    @property
    def full_location(self) -> str:
        if self.location_details:
            return f"{self.location_name} - {self.location_details}"
        return self.location_name or "TBD"


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
        }, timeout=10)
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
        }, timeout=10)
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
        response = requests.get(url, headers=headers, params=params, timeout=10)
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
        """
        Get full roster for a team.

        Per TEAMSNAP_SCHEMA.md, Member fields:
        - id, first_name, last_name, jersey_number (string!)
        - is_coach, is_owner, is_manager (use these to filter non-players)
        - email_addresses (list[str] - directly on member, not separate endpoint)
        - phone_numbers (list - directly on member)
        - birthday (string, often empty)
        """
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

            # Skip coaches/managers/owners - per schema these are the actual fields
            if member.get('is_coach', False) or \
               member.get('is_manager', False) or \
               member.get('is_owner', False):
                logger.debug(f"Skipping non-player: {member.get('first_name')} {member.get('last_name')}")
                continue

            # Email addresses are directly on member (list of strings per schema)
            email_addresses = member.get('email_addresses', [])
            if isinstance(email_addresses, str):
                email_addresses = [email_addresses] if email_addresses else []

            # Phone numbers directly on member (list per schema)
            phone_numbers = member.get('phone_numbers', [])
            if isinstance(phone_numbers, str):
                phone_numbers = [phone_numbers] if phone_numbers else []

            # jersey_number is STRING per schema - keep as-is
            jersey = member.get('jersey_number')

            # Note: 'position' is NOT in the schema - we can't determine goalkeeper from API
            # Would need to infer from jersey number convention or manual tagging

            players.append(TeamSnapPlayer(
                id=member['id'],
                first_name=member.get('first_name', ''),
                last_name=member.get('last_name', ''),
                jersey_number=jersey,  # String per schema
                position=None,  # Not available in API
                is_goalkeeper=False,  # Can't determine from API
                email_addresses=email_addresses,
                phone_numbers=phone_numbers,
                birthday=member.get('birthday', '')  # Often empty string
            ))

        logger.info(f"Fetched {len(players)} players for team {team_id}")
        return players

    def get_events(self, token: TeamSnapToken, team_id: int, games_only: bool = True) -> List[TeamSnapGame]:
        """
        Get events (games/practices) for a team.

        Per TEAMSNAP_SCHEMA.md, Event fields:
        - id, team_id, is_game, game_type, start_date
        - opponent_name, location_name, additional_location_details
        - points_for_team, points_for_opponent
        - is_canceled, formatted_title, uniform

        Args:
            token: OAuth token
            team_id: TeamSnap team ID
            games_only: If True, only return actual games (is_game=True)
        """
        if token.is_expired:
            token = self.refresh_token(token)

        events_data = self._api_request(
            token.access_token,
            '/events',
            params={'team_id': team_id}
        )

        games = []
        for item in events_data.get('collection', {}).get('items', []):
            event = {d['name']: d['value'] for d in item['data']}

            is_game = event.get('is_game', False)

            # Filter to games only if requested
            if games_only and not is_game:
                logger.debug(f"Skipping non-game event: {event.get('formatted_title')}")
                continue

            # Skip canceled games
            if event.get('is_canceled', False):
                logger.debug(f"Skipping canceled game: {event.get('formatted_title')}")
                continue

            # Parse start_date (ISO format per schema)
            start_date = None
            if event.get('start_date'):
                try:
                    start_date = datetime.fromisoformat(
                        event['start_date'].replace('Z', '+00:00')
                    )
                except (ValueError, AttributeError):
                    logger.warning(f"Failed to parse date: {event.get('start_date')}")

            games.append(TeamSnapGame(
                id=event['id'],
                team_id=event.get('team_id', team_id),
                is_game=is_game,
                game_type=event.get('game_type', 'Home'),  # "Home" or "Away"
                start_date=start_date,
                opponent_name=event.get('opponent_name'),
                location_name=event.get('location_name'),
                location_details=event.get('additional_location_details'),
                points_for_team=event.get('points_for_team'),
                points_for_opponent=event.get('points_for_opponent'),
                formatted_title=event.get('formatted_title'),
                is_canceled=event.get('is_canceled', False),
                uniform=event.get('uniform'),
                raw_data=event  # Store full response for JSONB
            ))

        logger.info(f"Fetched {len(games)} games for team {team_id}")
        return games

    # Note: _get_member_contacts removed - email_addresses and phone_numbers
    # are directly on the Member object per TEAMSNAP_SCHEMA.md


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
            logger.exception(f"Failed to fetch teams: {e}")
            return {'error': str(e)}

        synced = {
            'teams_created': 0,
            'teams_updated': 0,
            'players_created': 0,
            'players_updated': 0,
            'games_created': 0,
            'games_updated': 0,
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
            synced['games_created'] += result.get('games_created', 0)
            synced['games_updated'] += result.get('games_updated', 0)

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

        # Sync games/events
        ts_games = self.client.get_events(token, ts_team.id, games_only=True)
        games_created = 0
        games_updated = 0

        for ts_game in ts_games:
            game_result = self._sync_game(team, ts_game)
            if game_result.get('created'):
                games_created += 1
            else:
                games_updated += 1

        self.db.commit()

        return {
            'team_id': team.id,
            'name': team.name,
            'team_code': team.team_code,
            'created': created,
            'players_created': players_created,
            'players_updated': players_updated,
            'games_created': games_created,
            'games_updated': games_updated
        }

    def _sync_player(self, user, team, ts_player: TeamSnapPlayer) -> Dict:
        """
        Sync a player and link to team with jersey number.

        Note: Per TEAMSNAP_SCHEMA.md, 'position' is NOT available from TeamSnap API.
        Position must be set manually or inferred from jersey number conventions.
        """
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
            # Create new player - position not available from TeamSnap API
            # Could infer goalkeeper from jersey_number == "1" or "0" convention
            position = PlayerPosition.UNKNOWN
            if ts_player.jersey_number in ('0', '1', '00'):
                position = PlayerPosition.GOALKEEPER  # Common GK numbers

            player = Player(
                first_name=ts_player.first_name,
                last_name=ts_player.last_name,
                birth_year=ts_player.birth_year,  # None if unknown - don't fake it
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
        # Note: position stored as NULL since TeamSnap doesn't provide it
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
                    jersey_number=ts_player.jersey_number,  # String per schema
                    position=None,  # Not available from TeamSnap
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
                    jersey_number=ts_player.jersey_number
                    # Don't update position - would overwrite manual assignment
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

    def _sync_game(self, team, ts_game: TeamSnapGame) -> Dict:
        """
        Sync a game from TeamSnap.

        Note: This creates/updates games from TeamSnap schedule.
        Games are NOT automatically linked to recordings - that must be done
        manually or by matching session_id when a recording is created.
        """
        from ..models import Game

        # Find game by TeamSnap ID
        game = self.db.query(Game).filter(
            Game.teamsnap_event_id == ts_game.id
        ).first()

        created = False
        if not game:
            # Create new game record from TeamSnap
            game = Game(
                team_id=team.id,
                opponent=ts_game.opponent_name,
                location=ts_game.full_location,
                game_date=ts_game.start_date or datetime.utcnow(),
                game_type='league',  # Default, TeamSnap doesn't provide this
                is_home=ts_game.is_home,
                home_score=ts_game.points_for_team if ts_game.is_home else ts_game.points_for_opponent,
                away_score=ts_game.points_for_opponent if ts_game.is_home else ts_game.points_for_team,
                teamsnap_event_id=ts_game.id,
                teamsnap_data=ts_game.raw_data,
                is_processed=False  # No recording yet
            )
            self.db.add(game)
            self.db.flush()
            created = True
            logger.info(f"Created game: {team.name} vs {ts_game.opponent_name} ({ts_game.start_date})")
        else:
            # Update game info from TeamSnap
            game.opponent = ts_game.opponent_name
            game.location = ts_game.full_location
            game.game_date = ts_game.start_date or game.game_date
            game.is_home = ts_game.is_home
            # Update scores if TeamSnap has them
            if ts_game.points_for_team is not None:
                game.home_score = ts_game.points_for_team if ts_game.is_home else ts_game.points_for_opponent
                game.away_score = ts_game.points_for_opponent if ts_game.is_home else ts_game.points_for_team
            game.teamsnap_data = ts_game.raw_data  # Update JSONB

        return {'created': created, 'game_id': game.id}

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
        
        # Validate return_url to prevent open redirect
        return_url = request.args.get('return_url', '/')
        # Only allow relative URLs (no protocol, no double slashes)
        if not return_url.startswith('/') or '//' in return_url or ':' in return_url:
            return_url = '/'
        session['teamsnap_return_url'] = return_url

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

        # Require authentication
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401

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

        # Require authentication
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401

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

    # -------------------------------------------------------------------------
    # Games Schedule API
    # -------------------------------------------------------------------------

    @app.route('/api/games/schedule')
    def api_games_schedule():
        """
        Get all games - from TeamSnap and with recording status.

        Shows:
        - Team vs Opponent
        - Date/time
        - Location (home/away)
        - Whether recording exists (has video)
        - Link to video if available
        """
        from ..models import Game, Team
        from sqlalchemy import desc

        team_id = request.args.get('team_id', type=int)

        query = db.query(Game).join(Team)
        if team_id:
            query = query.filter(Game.team_id == team_id)

        games = query.order_by(desc(Game.game_date)).all()

        return jsonify({
            'count': len(games),
            'games': [
                {
                    'id': g.id,
                    'team': {
                        'id': g.team.id,
                        'name': g.team.name,
                        'team_code': g.team.team_code
                    },
                    'opponent': g.opponent,
                    'game_date': g.game_date.isoformat() if g.game_date else None,
                    'location': g.location,
                    'is_home': g.is_home,
                    'home_away': 'Home' if g.is_home else 'Away',
                    'score': {
                        'home': g.home_score,
                        'away': g.away_score,
                        'display': f"{g.home_score or '-'} - {g.away_score or '-'}"
                    },
                    # Recording/video info
                    'has_recording': g.session_id is not None,
                    'is_processed': g.is_processed,
                    'session_id': g.session_id,
                    'panorama_url': g.panorama_url,
                    'thumbnail_url': g.thumbnail_url,
                    # TeamSnap link
                    'from_teamsnap': g.teamsnap_event_id is not None,
                    'teamsnap_event_id': g.teamsnap_event_id,
                    # Status indicators
                    'status': _get_game_status(g)
                }
                for g in games
            ]
        })

    def _get_game_status(game):
        """Determine game status for display."""
        if game.is_processed and game.panorama_url:
            return 'ready'  # Video ready to view
        elif game.session_id:
            return 'processing'  # Has recording, being processed
        elif game.teamsnap_event_id:
            return 'scheduled'  # From TeamSnap, no recording yet
        else:
            return 'manual'  # Manually created game

    @app.route('/api/games/<int:game_id>')
    def api_game_detail(game_id):
        """Get detailed game info including video paths."""
        from ..models import Game, Recording

        game = db.query(Game).get(game_id)
        if not game:
            return jsonify({'error': 'Game not found'}), 404

        recordings = db.query(Recording).filter(Recording.game_id == game_id).all()

        return jsonify({
            'id': game.id,
            'team': {
                'id': game.team.id,
                'name': game.team.name
            },
            'opponent': game.opponent,
            'game_date': game.game_date.isoformat() if game.game_date else None,
            'location': game.location,
            'is_home': game.is_home,
            'score': {
                'home': game.home_score,
                'away': game.away_score
            },
            'duration_seconds': game.duration_seconds,
            # Video files
            'session_id': game.session_id,
            'panorama_url': game.panorama_url,
            'thumbnail_url': game.thumbnail_url,
            'is_processed': game.is_processed,
            'processed_at': game.processed_at.isoformat() if game.processed_at else None,
            # Individual camera recordings
            'recordings': [
                {
                    'id': r.id,
                    'camera_id': r.camera_id,
                    'camera_position': r.camera_position,
                    'file_path': r.file_path,
                    'file_size': r.file_size,
                    'duration_seconds': r.duration_seconds,
                    'resolution': r.resolution
                }
                for r in recordings
            ],
            # TeamSnap data
            'teamsnap_event_id': game.teamsnap_event_id,
            'teamsnap_data': game.teamsnap_data,
            # Metadata
            'game_metadata': game.game_metadata
        })

    @app.route('/api/games/<int:game_id>/link-recording', methods=['POST'])
    def api_link_recording(game_id):
        """
        Link a recording session to a game.

        Used when a recording was made but not auto-linked to TeamSnap game.
        """
        from ..models import Game

        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401

        game = db.query(Game).get(game_id)
        if not game:
            return jsonify({'error': 'Game not found'}), 404

        data = request.get_json()
        session_id = data.get('session_id')

        if not session_id:
            return jsonify({'error': 'session_id required'}), 400

        # Check session_id isn't already linked
        existing = db.query(Game).filter(Game.session_id == session_id).first()
        if existing and existing.id != game_id:
            return jsonify({
                'error': f'Session already linked to game {existing.id}'
            }), 400

        game.session_id = session_id
        db.commit()

        return jsonify({
            'success': True,
            'message': f'Linked session {session_id} to game {game_id}'
        })

    @app.route('/schedule')
    def schedule_page():
        """Games schedule page."""
        from flask import render_template_string

        return render_template_string(SCHEDULE_HTML)

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
# Schedule HTML Template
# =============================================================================

SCHEDULE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Game Schedule - Soccer Rig</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f0f4f8; color: #1a202c; min-height: 100vh; }
        .header { background: linear-gradient(135deg, #1a472a 0%, #2d5a27 100%); color: white; padding: 1.5rem 2rem; }
        .header-content { max-width: 1400px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; }
        .nav-links { display: flex; gap: 1.5rem; }
        .nav-links a { color: white; text-decoration: none; opacity: 0.8; }
        .nav-links a:hover { opacity: 1; }
        .container { max-width: 1400px; margin: 0 auto; padding: 2rem; }
        .filters { display: flex; gap: 1rem; margin-bottom: 1.5rem; flex-wrap: wrap; align-items: center; }
        .filter-group { display: flex; align-items: center; gap: 0.5rem; }
        .filter-group select { padding: 0.5rem; border: 2px solid #e2e8f0; border-radius: 0.5rem; }
        .status-legend { display: flex; gap: 1rem; margin-left: auto; }
        .legend-item { display: flex; align-items: center; gap: 0.25rem; font-size: 0.75rem; }
        .status-dot { width: 10px; height: 10px; border-radius: 50%; }
        .status-ready { background: #10b981; }
        .status-processing { background: #f59e0b; }
        .status-scheduled { background: #3b82f6; }
        .status-manual { background: #94a3b8; }
        table { width: 100%; border-collapse: collapse; background: white; border-radius: 1rem; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        th { background: #f8fafc; text-align: left; padding: 1rem; font-weight: 600; color: #64748b; border-bottom: 2px solid #e2e8f0; }
        td { padding: 1rem; border-bottom: 1px solid #e2e8f0; }
        tr:hover { background: #f8fafc; }
        .game-row { cursor: pointer; }
        .team-name { font-weight: 600; }
        .opponent { color: #374151; }
        .vs { color: #94a3b8; margin: 0 0.5rem; }
        .date { color: #64748b; font-size: 0.875rem; }
        .location { color: #64748b; font-size: 0.875rem; }
        .home-away { display: inline-block; padding: 0.25rem 0.5rem; border-radius: 0.25rem; font-size: 0.75rem; font-weight: 600; }
        .home { background: #dbeafe; color: #1d4ed8; }
        .away { background: #fef3c7; color: #92400e; }
        .score { font-weight: 700; font-size: 1.125rem; }
        .status-badge { display: inline-flex; align-items: center; gap: 0.25rem; padding: 0.25rem 0.5rem; border-radius: 0.25rem; font-size: 0.75rem; }
        .badge-ready { background: #d1fae5; color: #065f46; }
        .badge-processing { background: #fef3c7; color: #92400e; }
        .badge-scheduled { background: #dbeafe; color: #1d4ed8; }
        .badge-manual { background: #e2e8f0; color: #475569; }
        .video-link { color: #10b981; text-decoration: none; font-weight: 500; }
        .video-link:hover { text-decoration: underline; }
        .no-video { color: #94a3b8; font-style: italic; }
        .teamsnap-badge { background: #fef3c7; color: #92400e; padding: 0.125rem 0.375rem; border-radius: 0.25rem; font-size: 0.625rem; margin-left: 0.5rem; }
        .empty-state { text-align: center; padding: 4rem 2rem; color: #64748b; }
        .btn { padding: 0.5rem 1rem; border-radius: 0.5rem; border: none; cursor: pointer; font-weight: 500; text-decoration: none; }
        .btn-primary { background: #10b981; color: white; }
        .btn-secondary { background: #e2e8f0; color: #374151; }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-content">
            <h1>Game Schedule</h1>
            <div class="nav-links">
                <a href="/dashboard">Dashboard</a>
                <a href="/data-explorer">Data Explorer</a>
                <a href="/schedule">Schedule</a>
            </div>
        </div>
    </div>
    <div class="container">
        <div class="filters">
            <div class="filter-group">
                <label>Team:</label>
                <select id="team-filter" onchange="loadGames()">
                    <option value="">All Teams</option>
                </select>
            </div>
            <div class="filter-group">
                <label>Status:</label>
                <select id="status-filter" onchange="filterGames()">
                    <option value="">All</option>
                    <option value="ready">Ready to View</option>
                    <option value="processing">Processing</option>
                    <option value="scheduled">Scheduled</option>
                </select>
            </div>
            <button class="btn btn-secondary" onclick="loadGames()">Refresh</button>
            <div class="status-legend">
                <div class="legend-item"><span class="status-dot status-ready"></span> Video Ready</div>
                <div class="legend-item"><span class="status-dot status-processing"></span> Processing</div>
                <div class="legend-item"><span class="status-dot status-scheduled"></span> Scheduled</div>
                <div class="legend-item"><span class="status-dot status-manual"></span> No Video</div>
            </div>
        </div>

        <table>
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Match</th>
                    <th>Location</th>
                    <th>Score</th>
                    <th>Status</th>
                    <th>Video</th>
                </tr>
            </thead>
            <tbody id="games-table">
                <tr><td colspan="6" class="empty-state">Loading...</td></tr>
            </tbody>
        </table>
    </div>

    <script>
        let allGames = [];

        async function loadTeams() {
            try {
                const response = await fetch('/api/data/teams');
                const data = await response.json();
                const select = document.getElementById('team-filter');
                select.innerHTML = '<option value="">All Teams</option>' +
                    data.teams.map(t => `<option value="${t.id}">${t.name}</option>`).join('');
            } catch (error) {
                console.error('Failed to load teams:', error);
            }
        }

        async function loadGames() {
            try {
                const teamId = document.getElementById('team-filter').value;
                const url = teamId ? `/api/games/schedule?team_id=${teamId}` : '/api/games/schedule';
                const response = await fetch(url);
                const data = await response.json();
                allGames = data.games;
                filterGames();
            } catch (error) {
                console.error('Failed to load games:', error);
                document.getElementById('games-table').innerHTML =
                    '<tr><td colspan="6" class="empty-state">Failed to load games</td></tr>';
            }
        }

        function filterGames() {
            const statusFilter = document.getElementById('status-filter').value;
            let games = allGames;

            if (statusFilter) {
                games = games.filter(g => g.status === statusFilter);
            }

            renderGames(games);
        }

        function renderGames(games) {
            const tbody = document.getElementById('games-table');

            if (games.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No games found</td></tr>';
                return;
            }

            tbody.innerHTML = games.map(g => {
                const date = g.game_date ? new Date(g.game_date) : null;
                const dateStr = date ? date.toLocaleDateString('en-US', {
                    weekday: 'short', month: 'short', day: 'numeric', year: 'numeric'
                }) : 'TBD';
                const timeStr = date ? date.toLocaleTimeString('en-US', {
                    hour: 'numeric', minute: '2-digit'
                }) : '';

                const statusBadge = {
                    'ready': '<span class="status-badge badge-ready"><span class="status-dot status-ready"></span> Ready</span>',
                    'processing': '<span class="status-badge badge-processing"><span class="status-dot status-processing"></span> Processing</span>',
                    'scheduled': '<span class="status-badge badge-scheduled"><span class="status-dot status-scheduled"></span> Scheduled</span>',
                    'manual': '<span class="status-badge badge-manual"><span class="status-dot status-manual"></span> No Video</span>'
                }[g.status] || '';

                const videoLink = g.panorama_url
                    ? `<a href="${g.panorama_url}" class="video-link">Watch</a>`
                    : g.has_recording
                        ? '<span class="no-video">Processing...</span>'
                        : '<span class="no-video">-</span>';

                const teamsnapBadge = g.from_teamsnap ? '<span class="teamsnap-badge">TS</span>' : '';

                return `
                    <tr class="game-row" onclick="viewGame(${g.id})">
                        <td>
                            <div class="date">${dateStr}</div>
                            <div class="date">${timeStr}</div>
                        </td>
                        <td>
                            <span class="team-name">${g.team.name}</span>
                            <span class="vs">vs</span>
                            <span class="opponent">${g.opponent || 'TBD'}</span>
                            ${teamsnapBadge}
                        </td>
                        <td>
                            <span class="home-away ${g.is_home ? 'home' : 'away'}">${g.home_away}</span>
                            <div class="location">${g.location || 'TBD'}</div>
                        </td>
                        <td class="score">${g.score.display}</td>
                        <td>${statusBadge}</td>
                        <td>${videoLink}</td>
                    </tr>
                `;
            }).join('');
        }

        function viewGame(gameId) {
            // Could open a modal or navigate to game detail page
            console.log('View game:', gameId);
            // window.location.href = `/games/${gameId}`;
        }

        // Initial load
        loadTeams();
        loadGames();
    </script>
</body>
</html>
"""

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
