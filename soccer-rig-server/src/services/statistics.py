"""
Player Statistics Service

Aggregates player statistics from game events:
- Per-game stats (goals, assists, shots, saves, etc.)
- Season totals and averages
- Position-specific metrics (GK save %, striker conversion rate)
- Leaderboards and comparisons
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, date
from dataclasses import dataclass
from sqlalchemy import func, and_, desc
from sqlalchemy.orm import Session
import logging

logger = logging.getLogger(__name__)


@dataclass
class PlayerStats:
    """Player statistics summary."""
    player_id: int
    player_name: str
    games_played: int = 0
    minutes_played: int = 0

    # Offensive
    goals: int = 0
    assists: int = 0
    shots: int = 0
    shots_on_target: int = 0

    # Possession
    passes: int = 0
    dribbles: int = 0

    # Defensive
    tackles: int = 0
    interceptions: int = 0

    # Goalkeeper
    saves: int = 0
    saves_diving: int = 0
    goals_conceded: int = 0

    # Cards
    yellow_cards: int = 0
    red_cards: int = 0

    @property
    def goals_per_game(self) -> float:
        return round(self.goals / self.games_played, 2) if self.games_played else 0

    @property
    def shot_accuracy(self) -> float:
        return round(self.shots_on_target / self.shots * 100, 1) if self.shots else 0

    @property
    def save_percentage(self) -> float:
        total = self.saves + self.goals_conceded
        return round(self.saves / total * 100, 1) if total else 0

    def to_dict(self) -> Dict:
        return {
            'player_id': self.player_id,
            'player_name': self.player_name,
            'games_played': self.games_played,
            'minutes_played': self.minutes_played,
            'goals': self.goals,
            'assists': self.assists,
            'shots': self.shots,
            'shots_on_target': self.shots_on_target,
            'shot_accuracy': self.shot_accuracy,
            'passes': self.passes,
            'dribbles': self.dribbles,
            'tackles': self.tackles,
            'interceptions': self.interceptions,
            'saves': self.saves,
            'saves_diving': self.saves_diving,
            'goals_conceded': self.goals_conceded,
            'save_percentage': self.save_percentage,
            'yellow_cards': self.yellow_cards,
            'red_cards': self.red_cards,
            'goals_per_game': self.goals_per_game
        }


class StatisticsService:
    """
    Service for calculating and aggregating player statistics.

    Usage:
        stats_service = StatisticsService(db_session)

        # Get player's season stats
        stats = stats_service.get_player_season_stats(player_id, team_id, "Fall 2024")

        # Get game stats
        game_stats = stats_service.get_game_stats(game_id)

        # Recalculate after new events
        stats_service.recalculate_game_stats(game_id)
    """

    def __init__(self, db: Session):
        self.db = db

    # -------------------------------------------------------------------------
    # Game Statistics
    # -------------------------------------------------------------------------

    def recalculate_game_stats(self, game_id: int) -> Dict:
        """
        Recalculate all player stats for a game from events.
        Call this after ML processing adds new events.
        """
        from ..models import Game, GameEvent, PlayerGameStats, Player, EventType

        game = self.db.query(Game).get(game_id)
        if not game:
            return {'error': 'Game not found'}

        # Get all events for this game
        events = self.db.query(GameEvent).filter(
            GameEvent.game_id == game_id
        ).all()

        # Group events by player
        player_events: Dict[int, List[GameEvent]] = {}
        for event in events:
            if event.player_id:
                if event.player_id not in player_events:
                    player_events[event.player_id] = []
                player_events[event.player_id].append(event)

        stats_updated = 0

        for player_id, p_events in player_events.items():
            # Get or create stats record
            stats = self.db.query(PlayerGameStats).filter(
                and_(
                    PlayerGameStats.player_id == player_id,
                    PlayerGameStats.game_id == game_id
                )
            ).first()

            if not stats:
                stats = PlayerGameStats(
                    player_id=player_id,
                    game_id=game_id
                )
                self.db.add(stats)

            # Reset and recalculate
            stats.goals = 0
            stats.assists = 0
            stats.shots = 0
            stats.shots_on_target = 0
            stats.passes = 0
            stats.dribbles = 0
            stats.tackles = 0
            stats.interceptions = 0
            stats.saves = 0
            stats.saves_diving = 0
            stats.punches = 0
            stats.catches = 0
            stats.goals_conceded = 0
            stats.yellow_cards = 0
            stats.red_cards = 0
            stats.fouls = 0

            for event in p_events:
                self._add_event_to_stats(stats, event)

            # Calculate derived stats
            if stats.shots > 0:
                stats.pass_accuracy = None  # Would need pass success data
            if stats.saves + stats.goals_conceded > 0:
                stats.save_percentage = stats.saves / (stats.saves + stats.goals_conceded) * 100

            stats_updated += 1

        self.db.commit()

        # Also update season stats
        self._update_season_stats_for_game(game)

        return {
            'game_id': game_id,
            'players_updated': stats_updated,
            'total_events': len(events)
        }

    def _add_event_to_stats(self, stats, event) -> None:
        """Add a single event to player stats."""
        from ..models import EventType

        event_type = event.event_type

        if event_type == EventType.GOAL:
            stats.goals += 1
        elif event_type == EventType.ASSIST:
            stats.assists += 1
        elif event_type == EventType.SHOT:
            stats.shots += 1
        elif event_type == EventType.SHOT_ON_TARGET:
            stats.shots += 1
            stats.shots_on_target += 1
        elif event_type == EventType.PASS:
            stats.passes += 1
        elif event_type == EventType.DRIBBLE:
            stats.dribbles += 1
        elif event_type == EventType.TACKLE:
            stats.tackles += 1
        elif event_type == EventType.INTERCEPTION:
            stats.interceptions += 1
        elif event_type == EventType.SAVE:
            stats.saves += 1
        elif event_type == EventType.SAVE_DIVING:
            stats.saves += 1
            stats.saves_diving += 1
        elif event_type == EventType.SAVE_REFLEX:
            stats.saves += 1
        elif event_type == EventType.PUNCH:
            stats.punches += 1
        elif event_type == EventType.CATCH:
            stats.catches += 1
        elif event_type == EventType.YELLOW_CARD:
            stats.yellow_cards += 1
        elif event_type == EventType.RED_CARD:
            stats.red_cards += 1
        elif event_type == EventType.FOUL:
            stats.fouls += 1

    def get_game_stats(self, game_id: int) -> List[Dict]:
        """Get all player stats for a game."""
        from ..models import PlayerGameStats, Player

        stats = self.db.query(PlayerGameStats, Player).join(
            Player, PlayerGameStats.player_id == Player.id
        ).filter(
            PlayerGameStats.game_id == game_id
        ).order_by(desc(PlayerGameStats.goals)).all()

        return [
            {
                'player_id': s.player_id,
                'player_name': p.full_name,
                'goals': s.goals,
                'assists': s.assists,
                'shots': s.shots,
                'shots_on_target': s.shots_on_target,
                'passes': s.passes,
                'dribbles': s.dribbles,
                'tackles': s.tackles,
                'interceptions': s.interceptions,
                'saves': s.saves,
                'save_percentage': round(s.save_percentage, 1) if s.save_percentage else None,
                'yellow_cards': s.yellow_cards,
                'red_cards': s.red_cards
            }
            for s, p in stats
        ]

    # -------------------------------------------------------------------------
    # Season Statistics
    # -------------------------------------------------------------------------

    def _update_season_stats_for_game(self, game) -> None:
        """Update season stats for all players in a game."""
        from ..models import PlayerGameStats, PlayerSeasonStats, Team

        team = game.team
        season = team.season or f"Season {date.today().year}"

        # Get all player game stats for this game
        game_stats = self.db.query(PlayerGameStats).filter(
            PlayerGameStats.game_id == game.id
        ).all()

        for gs in game_stats:
            self._update_player_season_stats(gs.player_id, team.id, season)

    def _update_player_season_stats(self, player_id: int, team_id: int, season: str) -> None:
        """Recalculate season stats for a player."""
        from ..models import PlayerGameStats, PlayerSeasonStats, Game

        # Get or create season stats
        season_stats = self.db.query(PlayerSeasonStats).filter(
            and_(
                PlayerSeasonStats.player_id == player_id,
                PlayerSeasonStats.team_id == team_id,
                PlayerSeasonStats.season == season
            )
        ).first()

        if not season_stats:
            season_stats = PlayerSeasonStats(
                player_id=player_id,
                team_id=team_id,
                season=season
            )
            self.db.add(season_stats)

        # Aggregate from all games in season
        game_stats = self.db.query(PlayerGameStats).join(
            Game, PlayerGameStats.game_id == Game.id
        ).filter(
            and_(
                PlayerGameStats.player_id == player_id,
                Game.team_id == team_id
            )
        ).all()

        # Reset totals
        season_stats.games_played = len(game_stats)
        season_stats.goals = sum(gs.goals or 0 for gs in game_stats)
        season_stats.assists = sum(gs.assists or 0 for gs in game_stats)
        season_stats.shots = sum(gs.shots or 0 for gs in game_stats)
        season_stats.shots_on_target = sum(gs.shots_on_target or 0 for gs in game_stats)
        season_stats.passes = sum(gs.passes or 0 for gs in game_stats)
        season_stats.dribbles = sum(gs.dribbles or 0 for gs in game_stats)
        season_stats.tackles = sum(gs.tackles or 0 for gs in game_stats)
        season_stats.interceptions = sum(gs.interceptions or 0 for gs in game_stats)
        season_stats.saves = sum(gs.saves or 0 for gs in game_stats)
        season_stats.goals_conceded = sum(gs.goals_conceded or 0 for gs in game_stats)
        season_stats.yellow_cards = sum(gs.yellow_cards or 0 for gs in game_stats)
        season_stats.red_cards = sum(gs.red_cards or 0 for gs in game_stats)
        season_stats.minutes_played = sum(gs.minutes_played or 0 for gs in game_stats)

        # Calculate averages
        if season_stats.games_played > 0:
            season_stats.goals_per_game = season_stats.goals / season_stats.games_played
            season_stats.assists_per_game = season_stats.assists / season_stats.games_played

        # Save percentage for goalkeepers
        total_shots_faced = season_stats.saves + season_stats.goals_conceded
        if total_shots_faced > 0:
            season_stats.save_percentage = (season_stats.saves / total_shots_faced) * 100

        self.db.commit()

    def get_player_season_stats(self, player_id: int, team_id: int, season: str) -> Optional[Dict]:
        """Get a player's season statistics."""
        from ..models import PlayerSeasonStats, Player

        stats = self.db.query(PlayerSeasonStats, Player).join(
            Player, PlayerSeasonStats.player_id == Player.id
        ).filter(
            and_(
                PlayerSeasonStats.player_id == player_id,
                PlayerSeasonStats.team_id == team_id,
                PlayerSeasonStats.season == season
            )
        ).first()

        if not stats:
            return None

        s, p = stats
        return {
            'player_id': p.id,
            'player_name': p.full_name,
            'birth_year': p.birth_year,
            'team_id': team_id,
            'season': season,
            'games_played': s.games_played,
            'minutes_played': s.minutes_played,
            'goals': s.goals,
            'assists': s.assists,
            'goals_per_game': round(s.goals_per_game, 2) if s.goals_per_game else 0,
            'assists_per_game': round(s.assists_per_game, 2) if s.assists_per_game else 0,
            'shots': s.shots,
            'shots_on_target': s.shots_on_target,
            'shot_accuracy': round(s.shots_on_target / s.shots * 100, 1) if s.shots else 0,
            'passes': s.passes,
            'dribbles': s.dribbles,
            'tackles': s.tackles,
            'interceptions': s.interceptions,
            'saves': s.saves,
            'goals_conceded': s.goals_conceded,
            'save_percentage': round(s.save_percentage, 1) if s.save_percentage else None,
            'yellow_cards': s.yellow_cards,
            'red_cards': s.red_cards
        }

    def get_team_season_stats(self, team_id: int, season: str) -> List[Dict]:
        """Get all players' season stats for a team."""
        from ..models import PlayerSeasonStats, Player

        stats = self.db.query(PlayerSeasonStats, Player).join(
            Player, PlayerSeasonStats.player_id == Player.id
        ).filter(
            and_(
                PlayerSeasonStats.team_id == team_id,
                PlayerSeasonStats.season == season
            )
        ).order_by(desc(PlayerSeasonStats.goals)).all()

        return [
            self.get_player_season_stats(s.player_id, team_id, season)
            for s, p in stats
        ]

    # -------------------------------------------------------------------------
    # Leaderboards
    # -------------------------------------------------------------------------

    def get_team_leaderboard(
        self,
        team_id: int,
        season: str,
        stat: str = 'goals',
        limit: int = 10
    ) -> List[Dict]:
        """Get leaderboard for a specific stat."""
        from ..models import PlayerSeasonStats, Player

        # Map stat name to column
        stat_columns = {
            'goals': PlayerSeasonStats.goals,
            'assists': PlayerSeasonStats.assists,
            'saves': PlayerSeasonStats.saves,
            'shots': PlayerSeasonStats.shots,
            'tackles': PlayerSeasonStats.tackles,
            'interceptions': PlayerSeasonStats.interceptions,
            'goals_per_game': PlayerSeasonStats.goals_per_game,
            'save_percentage': PlayerSeasonStats.save_percentage
        }

        column = stat_columns.get(stat, PlayerSeasonStats.goals)

        results = self.db.query(PlayerSeasonStats, Player).join(
            Player, PlayerSeasonStats.player_id == Player.id
        ).filter(
            and_(
                PlayerSeasonStats.team_id == team_id,
                PlayerSeasonStats.season == season
            )
        ).order_by(desc(column)).limit(limit).all()

        return [
            {
                'rank': i + 1,
                'player_id': p.id,
                'player_name': p.full_name,
                'value': getattr(s, stat) or 0,
                'games_played': s.games_played
            }
            for i, (s, p) in enumerate(results)
        ]

    def get_player_game_history(
        self,
        player_id: int,
        team_id: Optional[int] = None,
        limit: int = 20
    ) -> List[Dict]:
        """Get a player's recent game-by-game stats."""
        from ..models import PlayerGameStats, Game, Team

        query = self.db.query(PlayerGameStats, Game, Team).join(
            Game, PlayerGameStats.game_id == Game.id
        ).join(
            Team, Game.team_id == Team.id
        ).filter(
            PlayerGameStats.player_id == player_id
        )

        if team_id:
            query = query.filter(Game.team_id == team_id)

        results = query.order_by(desc(Game.game_date)).limit(limit).all()

        return [
            {
                'game_id': g.id,
                'date': g.game_date.isoformat() if g.game_date else None,
                'opponent': g.opponent,
                'team_name': t.name,
                'goals': s.goals,
                'assists': s.assists,
                'shots': s.shots,
                'saves': s.saves,
                'rating': s.rating
            }
            for s, g, t in results
        ]

    # -------------------------------------------------------------------------
    # Comparisons
    # -------------------------------------------------------------------------

    def compare_players(
        self,
        player_ids: List[int],
        team_id: int,
        season: str
    ) -> List[Dict]:
        """Compare multiple players' stats."""
        return [
            self.get_player_season_stats(pid, team_id, season)
            for pid in player_ids
        ]

    def get_player_percentiles(
        self,
        player_id: int,
        team_id: int,
        season: str
    ) -> Dict:
        """Get player's percentile rankings within the team."""
        from ..models import PlayerSeasonStats

        player_stats = self.db.query(PlayerSeasonStats).filter(
            and_(
                PlayerSeasonStats.player_id == player_id,
                PlayerSeasonStats.team_id == team_id,
                PlayerSeasonStats.season == season
            )
        ).first()

        if not player_stats:
            return {}

        all_stats = self.db.query(PlayerSeasonStats).filter(
            and_(
                PlayerSeasonStats.team_id == team_id,
                PlayerSeasonStats.season == season
            )
        ).all()

        if len(all_stats) < 2:
            return {}

        def percentile(value, all_values):
            if not all_values or value is None:
                return 0
            below = sum(1 for v in all_values if v is not None and v < value)
            return round(below / len(all_values) * 100)

        return {
            'goals': percentile(player_stats.goals, [s.goals for s in all_stats]),
            'assists': percentile(player_stats.assists, [s.assists for s in all_stats]),
            'shots': percentile(player_stats.shots, [s.shots for s in all_stats]),
            'tackles': percentile(player_stats.tackles, [s.tackles for s in all_stats]),
            'saves': percentile(player_stats.saves, [s.saves for s in all_stats])
        }


# =============================================================================
# Flask Routes
# =============================================================================

def register_statistics_routes(app, db):
    """Register statistics API routes."""
    from flask import jsonify, request, session, g
    from ..auth import get_user_team_ids

    stats_service = StatisticsService(db)

    # -------------------------------------------------------------------------
    # Authorization Helpers
    # -------------------------------------------------------------------------

    def _require_auth():
        """Check if user is authenticated, return user_id or None."""
        user_id = session.get('user_id')
        if not user_id:
            return None, (jsonify({'error': 'Not authenticated'}), 401)
        return user_id, None

    def _get_authorized_team_ids(user_id: int) -> set:
        """Get authorized team IDs, cached per request."""
        if not hasattr(g, '_stats_authorized_team_ids'):
            g._stats_authorized_team_ids = get_user_team_ids(db, user_id)
        return g._stats_authorized_team_ids

    def _user_can_access_team(user_id: int, team_id: int) -> bool:
        """Check if user has access to view team's stats."""
        return team_id in _get_authorized_team_ids(user_id)

    def _user_can_access_game(user_id: int, game_id: int) -> bool:
        """Check if user has access to view game's stats."""
        from ..models import Game
        db_session = db()
        try:
            game = db_session.get(Game, game_id)
            if not game:
                return False
            return game.team_id in _get_authorized_team_ids(user_id)
        finally:
            db_session.close()

    def _user_can_access_player(user_id: int, player_id: int) -> bool:
        """Check if user has access to view player's stats."""
        from ..models import Player
        db_session = db()
        try:
            player = db_session.get(Player, player_id)
            if not player:
                return False
            authorized_team_ids = _get_authorized_team_ids(user_id)
            return any(team.id in authorized_team_ids for team in player.teams)
        finally:
            db_session.close()

    # -------------------------------------------------------------------------
    # Game Stats Endpoints
    # -------------------------------------------------------------------------

    @app.route('/api/stats/game/<int:game_id>')
    def get_game_stats(game_id: int):
        """Get all player stats for a game."""
        user_id, error = _require_auth()
        if error:
            return error

        if not _user_can_access_game(user_id, game_id):
            return jsonify({'error': 'Access denied to this game'}), 403

        stats = stats_service.get_game_stats(game_id)
        return jsonify({'game_id': game_id, 'players': stats})

    @app.route('/api/stats/game/<int:game_id>/recalculate', methods=['POST'])
    def recalculate_game_stats(game_id: int):
        """Recalculate stats from events (after ML processing)."""
        from ..models import Game

        user_id, error = _require_auth()
        if error:
            return error

        # Check existence first, then authorization
        db_session = db()
        try:
            game = db_session.get(Game, game_id)
            if not game:
                return jsonify({'error': 'Game not found'}), 404

            if game.team_id not in _get_authorized_team_ids(user_id):
                return jsonify({'error': 'Access denied to this game'}), 403
        finally:
            db_session.close()

        result = stats_service.recalculate_game_stats(game_id)
        return jsonify(result)

    # -------------------------------------------------------------------------
    # Player Stats Endpoints
    # -------------------------------------------------------------------------

    @app.route('/api/stats/player/<int:player_id>')
    def get_player_stats(player_id: int):
        """Get player's stats (optionally filtered by team/season)."""
        user_id, error = _require_auth()
        if error:
            return error

        if not _user_can_access_player(user_id, player_id):
            return jsonify({'error': 'Access denied to this player'}), 403

        team_id = request.args.get('team_id', type=int)
        season = request.args.get('season', f"Season {date.today().year}")

        if team_id:
            # Also verify access to the specific team
            if not _user_can_access_team(user_id, team_id):
                return jsonify({'error': 'Access denied to this team'}), 403
            stats = stats_service.get_player_season_stats(player_id, team_id, season)
        else:
            # Get stats across all teams user has access to
            from ..models import Player
            player = db.query(Player).get(player_id)
            if not player:
                return jsonify({'error': 'Player not found'}), 404

            authorized_team_ids = _get_authorized_team_ids(user_id)
            stats = {
                'player_id': player_id,
                'player_name': player.full_name,
                'teams': []
            }
            for team in player.teams:
                if team.id in authorized_team_ids:
                    team_stats = stats_service.get_player_season_stats(
                        player_id, team.id, team.season or season
                    )
                    if team_stats:
                        stats['teams'].append(team_stats)

        return jsonify(stats)

    @app.route('/api/stats/player/<int:player_id>/history')
    def get_player_history(player_id: int):
        """Get player's game-by-game history."""
        user_id, error = _require_auth()
        if error:
            return error

        if not _user_can_access_player(user_id, player_id):
            return jsonify({'error': 'Access denied to this player'}), 403

        team_id = request.args.get('team_id', type=int)
        if team_id and not _user_can_access_team(user_id, team_id):
            return jsonify({'error': 'Access denied to this team'}), 403

        limit = request.args.get('limit', 20, type=int)

        history = stats_service.get_player_game_history(player_id, team_id, limit)
        return jsonify({'player_id': player_id, 'games': history})

    @app.route('/api/stats/player/<int:player_id>/percentiles')
    def get_player_percentiles(player_id: int):
        """Get player's percentile rankings."""
        user_id, error = _require_auth()
        if error:
            return error

        if not _user_can_access_player(user_id, player_id):
            return jsonify({'error': 'Access denied to this player'}), 403

        team_id = request.args.get('team_id', type=int)
        season = request.args.get('season')

        if not team_id or not season:
            return jsonify({'error': 'team_id and season required'}), 400

        if not _user_can_access_team(user_id, team_id):
            return jsonify({'error': 'Access denied to this team'}), 403

        percentiles = stats_service.get_player_percentiles(player_id, team_id, season)
        return jsonify({'player_id': player_id, 'percentiles': percentiles})

    # -------------------------------------------------------------------------
    # Team Stats Endpoints
    # -------------------------------------------------------------------------

    @app.route('/api/stats/team/<int:team_id>')
    def get_team_stats(team_id: int):
        """Get all player stats for a team."""
        user_id, error = _require_auth()
        if error:
            return error

        # Check existence before access (returns 404 for non-existent, not 403)
        from ..models import Team
        db_session = db()
        try:
            team = db_session.get(Team, team_id)
            if not team:
                return jsonify({'error': 'Team not found'}), 404

            if not _user_can_access_team(user_id, team_id):
                return jsonify({'error': 'Access denied to this team'}), 403

            season = request.args.get('season', team.season or f"Season {date.today().year}")
        finally:
            db_session.close()

        stats = stats_service.get_team_season_stats(team_id, season)

        return jsonify({
            'team_id': team_id,
            'team_name': team.name,
            'season': season,
            'players': stats
        })

    @app.route('/api/stats/team/<int:team_id>/leaderboard')
    def get_leaderboard(team_id: int):
        """Get team leaderboard for a stat."""
        user_id, error = _require_auth()
        if error:
            return error

        if not _user_can_access_team(user_id, team_id):
            return jsonify({'error': 'Access denied to this team'}), 403

        from ..models import Team
        team = db.query(Team).get(team_id)
        if not team:
            return jsonify({'error': 'Team not found'}), 404

        season = request.args.get('season', team.season or f"Season {date.today().year}")
        stat = request.args.get('stat', 'goals')
        limit = request.args.get('limit', 10, type=int)

        leaderboard = stats_service.get_team_leaderboard(team_id, season, stat, limit)

        return jsonify({
            'team_id': team_id,
            'season': season,
            'stat': stat,
            'leaderboard': leaderboard
        })

    @app.route('/api/stats/compare')
    def compare_players():
        """Compare multiple players."""
        user_id, error = _require_auth()
        if error:
            return error

        player_ids = request.args.getlist('player_id', type=int)
        team_id = request.args.get('team_id', type=int)
        season = request.args.get('season')

        if not player_ids or not team_id or not season:
            return jsonify({'error': 'player_id[], team_id, and season required'}), 400

        # Limit number of players to prevent abuse
        if len(player_ids) > 20:
            return jsonify({'error': 'Maximum 20 players can be compared'}), 400

        if not _user_can_access_team(user_id, team_id):
            return jsonify({'error': 'Access denied to this team'}), 403

        # Verify access to all requested players
        for player_id in player_ids:
            if not _user_can_access_player(user_id, player_id):
                return jsonify({'error': f'Access denied to player {player_id}'}), 403

        comparison = stats_service.compare_players(player_ids, team_id, season)
        return jsonify({'players': comparison})

