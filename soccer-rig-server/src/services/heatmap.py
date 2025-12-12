"""
Heat Map Generation Service

Generates player positioning heat maps from event data:
- Per-player heat maps showing movement patterns
- Team-wide positioning visualization
- Time-slice filtering (first half, second half, etc.)
- Interactive canvas with field overlay
"""

import math
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)

# Field dimensions (normalized 0-1)
FIELD_WIDTH = 1.0
FIELD_HEIGHT = 0.65  # Standard soccer field ratio


@dataclass
class PositionPoint:
    """A single position data point."""
    x: float  # 0-1 normalized
    y: float  # 0-1 normalized
    timestamp: float  # Seconds into game
    event_type: Optional[str] = None
    weight: float = 1.0  # For importance weighting


@dataclass
class HeatMapData:
    """Heat map data for rendering."""
    player_id: int
    player_name: str
    points: List[PositionPoint]
    grid: List[List[float]]  # 2D intensity grid
    max_intensity: float
    game_id: Optional[int] = None
    time_range: Optional[Tuple[float, float]] = None


class HeatMapService:
    """
    Service for generating player positioning heat maps.

    Usage:
        service = HeatMapService(db)

        # Get heat map for a player in a game
        heatmap = service.generate_player_heatmap(player_id, game_id)

        # Get team heat map
        team_heatmap = service.generate_team_heatmap(game_id)
    """

    # Grid resolution for heat map
    GRID_WIDTH = 50
    GRID_HEIGHT = 32

    # Gaussian blur radius for smoothing
    BLUR_RADIUS = 2

    def __init__(self, db):
        self.db = db

    def generate_player_heatmap(
        self,
        player_id: int,
        game_id: Optional[int] = None,
        time_start: Optional[float] = None,
        time_end: Optional[float] = None
    ) -> Optional[HeatMapData]:
        """
        Generate heat map for a single player.

        Args:
            player_id: Player ID
            game_id: Optional game ID (if None, aggregates all games)
            time_start: Optional start time in seconds
            time_end: Optional end time in seconds

        Returns:
            HeatMapData with intensity grid
        """
        from ..models import Player, GameEvent

        player = self.db.query(Player).get(player_id)
        if not player:
            return None

        # Get position data from events
        query = self.db.query(GameEvent).filter(
            GameEvent.player_id == player_id,
            GameEvent.field_position_x.isnot(None),
            GameEvent.field_position_y.isnot(None)
        )

        if game_id:
            query = query.filter(GameEvent.game_id == game_id)

        events = query.all()

        # Convert to position points
        points = []
        for event in events:
            # Apply time filter
            if time_start and event.timestamp_seconds < time_start:
                continue
            if time_end and event.timestamp_seconds > time_end:
                continue

            # Weight by event importance
            weight = self._get_event_weight(event.event_type.value if event.event_type else None)

            points.append(PositionPoint(
                x=event.field_position_x,
                y=event.field_position_y,
                timestamp=event.timestamp_seconds,
                event_type=event.event_type.value if event.event_type else None,
                weight=weight
            ))

        if not points:
            # Return empty heat map
            return HeatMapData(
                player_id=player_id,
                player_name=player.full_name,
                points=[],
                grid=self._empty_grid(),
                max_intensity=0,
                game_id=game_id,
                time_range=(time_start, time_end) if time_start or time_end else None
            )

        # Generate intensity grid
        grid = self._generate_grid(points)
        max_intensity = max(max(row) for row in grid) if grid else 0

        return HeatMapData(
            player_id=player_id,
            player_name=player.full_name,
            points=points,
            grid=grid,
            max_intensity=max_intensity,
            game_id=game_id,
            time_range=(time_start, time_end) if time_start or time_end else None
        )

    def generate_team_heatmap(
        self,
        team_id: int,
        game_id: Optional[int] = None,
        exclude_goalkeeper: bool = True
    ) -> Dict[str, HeatMapData]:
        """
        Generate heat maps for all players on a team.

        Returns dict mapping player_id to HeatMapData.
        """
        from ..models import Team, Player, team_player

        team = self.db.query(Team).get(team_id)
        if not team:
            return {}

        result = {}
        for player in team.players:
            # Optionally skip goalkeepers
            if exclude_goalkeeper and player.default_position and \
               player.default_position.value == 'goalkeeper':
                continue

            heatmap = self.generate_player_heatmap(player.id, game_id)
            if heatmap:
                result[player.id] = heatmap

        return result

    def generate_combined_heatmap(
        self,
        game_id: int,
        team_id: Optional[int] = None
    ) -> HeatMapData:
        """
        Generate a combined heat map for all players in a game.
        Shows overall team positioning.
        """
        from ..models import GameEvent, Game

        game = self.db.query(Game).get(game_id)
        if not game:
            return None

        query = self.db.query(GameEvent).filter(
            GameEvent.game_id == game_id,
            GameEvent.field_position_x.isnot(None),
            GameEvent.field_position_y.isnot(None)
        )

        if team_id:
            from ..models import Player, team_player
            from sqlalchemy import and_

            # Filter to players on this team
            player_ids = [p.id for p in self.db.query(Player).join(
                team_player, Player.id == team_player.c.player_id
            ).filter(team_player.c.team_id == team_id).all()]

            query = query.filter(GameEvent.player_id.in_(player_ids))

        events = query.all()

        points = [
            PositionPoint(
                x=e.field_position_x,
                y=e.field_position_y,
                timestamp=e.timestamp_seconds,
                event_type=e.event_type.value if e.event_type else None,
                weight=self._get_event_weight(e.event_type.value if e.event_type else None)
            )
            for e in events
        ]

        grid = self._generate_grid(points) if points else self._empty_grid()
        max_intensity = max(max(row) for row in grid) if grid else 0

        return HeatMapData(
            player_id=0,  # Combined
            player_name="Team",
            points=points,
            grid=grid,
            max_intensity=max_intensity,
            game_id=game_id
        )

    def _generate_grid(self, points: List[PositionPoint]) -> List[List[float]]:
        """Generate intensity grid from position points."""
        grid = self._empty_grid()

        for point in points:
            # Map point to grid cell
            gx = int(point.x * (self.GRID_WIDTH - 1))
            gy = int(point.y * (self.GRID_HEIGHT - 1))

            # Clamp to valid range
            gx = max(0, min(self.GRID_WIDTH - 1, gx))
            gy = max(0, min(self.GRID_HEIGHT - 1, gy))

            # Add weighted intensity with gaussian spread
            for dx in range(-self.BLUR_RADIUS, self.BLUR_RADIUS + 1):
                for dy in range(-self.BLUR_RADIUS, self.BLUR_RADIUS + 1):
                    nx, ny = gx + dx, gy + dy
                    if 0 <= nx < self.GRID_WIDTH and 0 <= ny < self.GRID_HEIGHT:
                        # Gaussian falloff
                        dist = math.sqrt(dx*dx + dy*dy)
                        falloff = math.exp(-dist*dist / (2 * self.BLUR_RADIUS))
                        grid[ny][nx] += point.weight * falloff

        return grid

    def _empty_grid(self) -> List[List[float]]:
        """Create empty intensity grid."""
        return [[0.0] * self.GRID_WIDTH for _ in range(self.GRID_HEIGHT)]

    def _get_event_weight(self, event_type: Optional[str]) -> float:
        """Get importance weight for event type."""
        weights = {
            'goal': 3.0,
            'shot': 2.0,
            'shot_on_target': 2.0,
            'assist': 2.0,
            'save': 2.5,
            'save_diving': 2.5,
            'tackle': 1.5,
            'interception': 1.5,
            'pass': 0.5,
            'dribble': 1.0,
        }
        return weights.get(event_type, 1.0)

    def to_canvas_data(self, heatmap: HeatMapData) -> Dict:
        """
        Convert heat map to format suitable for canvas rendering.

        Returns JSON-serializable dict with:
        - grid: 2D intensity array (normalized 0-1)
        - points: List of event points for overlay
        - meta: Player/game info
        """
        # Normalize grid to 0-1
        normalized_grid = []
        max_val = heatmap.max_intensity or 1

        for row in heatmap.grid:
            normalized_grid.append([v / max_val for v in row])

        return {
            'grid': normalized_grid,
            'gridWidth': self.GRID_WIDTH,
            'gridHeight': self.GRID_HEIGHT,
            'points': [
                {
                    'x': p.x,
                    'y': p.y,
                    'type': p.event_type,
                    'time': p.timestamp
                }
                for p in heatmap.points
            ],
            'meta': {
                'playerId': heatmap.player_id,
                'playerName': heatmap.player_name,
                'gameId': heatmap.game_id,
                'maxIntensity': heatmap.max_intensity,
                'pointCount': len(heatmap.points)
            }
        }


# =============================================================================
# Flask Routes
# =============================================================================

def register_heatmap_routes(app, db):
    """Register heat map API routes."""
    from flask import jsonify, request, render_template_string, session, redirect, url_for
    from ..auth import get_user_team_ids

    service = HeatMapService(db)

    def _user_can_access_player(user_id: int, player_id: int) -> bool:
        """Check if user has access to view player's heatmap."""
        from ..models import Player
        player = db.query(Player).get(player_id)
        if not player:
            return False
        
        authorized_team_ids = get_user_team_ids(db, user_id)
        # User can access player if player is on any of user's teams
        for team in player.teams:
            if team.id in authorized_team_ids:
                return True
        return False

    def _user_can_access_team(user_id: int, team_id: int) -> bool:
        """Check if user has access to view team's heatmap."""
        authorized_team_ids = get_user_team_ids(db, user_id)
        return team_id in authorized_team_ids

    def _user_can_access_game(user_id: int, game_id: int) -> bool:
        """Check if user has access to view game's heatmap."""
        from ..models import Game
        game = db.query(Game).get(game_id)
        if not game:
            return False
        authorized_team_ids = get_user_team_ids(db, user_id)
        return game.team_id in authorized_team_ids

    @app.route('/api/heatmap/player/<int:player_id>')
    def api_player_heatmap(player_id: int):
        """Get heat map data for a player."""
        # Require authentication
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401

        # Authorization: check user has access to this player
        if not _user_can_access_player(user_id, player_id):
            return jsonify({'error': 'Access denied to this player'}), 403

        game_id = request.args.get('game_id', type=int)
        time_start = request.args.get('time_start', type=float)
        time_end = request.args.get('time_end', type=float)

        heatmap = service.generate_player_heatmap(
            player_id, game_id, time_start, time_end
        )

        if not heatmap:
            return jsonify({'error': 'Player not found'}), 404

        return jsonify(service.to_canvas_data(heatmap))

    @app.route('/api/heatmap/team/<int:team_id>')
    def api_team_heatmap(team_id: int):
        """Get heat maps for all players on a team."""
        # Require authentication
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401

        # Authorization: check user has access to this team
        if not _user_can_access_team(user_id, team_id):
            return jsonify({'error': 'Access denied to this team'}), 403

        game_id = request.args.get('game_id', type=int)

        heatmaps = service.generate_team_heatmap(team_id, game_id)

        return jsonify({
            'players': {
                pid: service.to_canvas_data(hm)
                for pid, hm in heatmaps.items()
            }
        })

    @app.route('/api/heatmap/game/<int:game_id>')
    def api_game_heatmap(game_id: int):
        """Get combined heat map for a game."""
        # Require authentication
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401

        # Authorization: check user has access to this game
        if not _user_can_access_game(user_id, game_id):
            return jsonify({'error': 'Access denied to this game'}), 403

        team_id = request.args.get('team_id', type=int)

        heatmap = service.generate_combined_heatmap(game_id, team_id)

        if not heatmap:
            return jsonify({'error': 'Game not found'}), 404

        return jsonify(service.to_canvas_data(heatmap))

    @app.route('/heatmap/player/<int:player_id>')
    def view_player_heatmap(player_id: int):
        """Interactive heat map viewer."""
        # Require authentication for viewer page
        user_id = session.get('user_id')
        if not user_id:
            return redirect(url_for('login'))

        # Authorization: check user has access to this player
        if not _user_can_access_player(user_id, player_id):
            return "Access denied", 403

        game_id = request.args.get('game_id', type=int)

        return render_template_string(
            HEATMAP_VIEWER_HTML,
            player_id=player_id,
            game_id=game_id
        )


# =============================================================================
# Heat Map Viewer HTML
# =============================================================================

HEATMAP_VIEWER_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Heat Map - Soccer Rig</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0f172a; color: #f1f5f9; min-height: 100vh; padding: 2rem; }
        .container { max-width: 1000px; margin: 0 auto; }
        h1 { margin-bottom: 1rem; }
        .controls { display: flex; gap: 1rem; margin-bottom: 1rem; flex-wrap: wrap; }
        .controls select, .controls button { padding: 0.5rem 1rem; border-radius: 0.5rem; border: 1px solid #334155; background: #1e293b; color: #f1f5f9; }
        .field-container { position: relative; width: 100%; max-width: 800px; margin: 0 auto; }
        #heatmap-canvas { width: 100%; border-radius: 0.5rem; background: #1a472a; }
        .legend { display: flex; align-items: center; gap: 0.5rem; margin-top: 1rem; justify-content: center; }
        .legend-gradient { width: 200px; height: 20px; border-radius: 4px; background: linear-gradient(to right, rgba(0,0,255,0), rgba(0,0,255,0.5), rgba(0,255,0,0.5), rgba(255,255,0,0.5), rgba(255,0,0,0.8)); }
        .meta { margin-top: 1rem; text-align: center; color: #94a3b8; }
    </style>
</head>
<body>
    <div class="container">
        <h1>⚽ Player Heat Map</h1>

        <div class="controls">
            <select id="time-filter">
                <option value="all">Full Game</option>
                <option value="first">First Half (0-45 min)</option>
                <option value="second">Second Half (45-90 min)</option>
                <option value="last15">Last 15 Minutes</option>
            </select>
            <button onclick="loadHeatmap()">Refresh</button>
        </div>

        <div class="field-container">
            <canvas id="heatmap-canvas" width="800" height="520"></canvas>
        </div>

        <div class="legend">
            <span>Low</span>
            <div class="legend-gradient"></div>
            <span>High</span>
        </div>

        <div class="meta" id="meta">Loading...</div>
    </div>

    <script>
        const canvas = document.getElementById('heatmap-canvas');
        const ctx = canvas.getContext('2d');
        const playerId = {{ player_id }};
        const gameId = {{ game_id or 'null' }};

        function loadHeatmap() {
            const timeFilter = document.getElementById('time-filter').value;
            let url = `/api/heatmap/player/${playerId}`;
            const params = new URLSearchParams();

            if (gameId) params.append('game_id', gameId);

            if (timeFilter === 'first') {
                params.append('time_start', '0');
                params.append('time_end', '2700');
            } else if (timeFilter === 'second') {
                params.append('time_start', '2700');
                params.append('time_end', '5400');
            } else if (timeFilter === 'last15') {
                params.append('time_start', '4500');
            }

            if (params.toString()) url += '?' + params.toString();

            fetch(url)
                .then(r => r.json())
                .then(data => renderHeatmap(data))
                .catch(e => console.error('Failed to load heatmap', e));
        }

        function renderHeatmap(data) {
            // Clear canvas
            ctx.clearRect(0, 0, canvas.width, canvas.height);

            // Draw field
            drawField();

            // Draw heat map
            const cellWidth = canvas.width / data.gridWidth;
            const cellHeight = canvas.height / data.gridHeight;

            for (let y = 0; y < data.gridHeight; y++) {
                for (let x = 0; x < data.gridWidth; x++) {
                    const intensity = data.grid[y][x];
                    if (intensity > 0.05) {
                        ctx.fillStyle = getHeatColor(intensity);
                        ctx.fillRect(x * cellWidth, y * cellHeight, cellWidth + 1, cellHeight + 1);
                    }
                }
            }

            // Draw event points
            ctx.fillStyle = 'white';
            for (const point of data.points) {
                const px = point.x * canvas.width;
                const py = point.y * canvas.height;
                ctx.beginPath();
                ctx.arc(px, py, 3, 0, Math.PI * 2);
                ctx.fill();
            }

            // Update meta
            document.getElementById('meta').textContent =
                `${data.meta.playerName} • ${data.meta.pointCount} events`;
        }

        function drawField() {
            ctx.strokeStyle = 'rgba(255,255,255,0.3)';
            ctx.lineWidth = 2;

            // Outer boundary
            ctx.strokeRect(20, 20, canvas.width - 40, canvas.height - 40);

            // Center line
            ctx.beginPath();
            ctx.moveTo(canvas.width / 2, 20);
            ctx.lineTo(canvas.width / 2, canvas.height - 20);
            ctx.stroke();

            // Center circle
            ctx.beginPath();
            ctx.arc(canvas.width / 2, canvas.height / 2, 60, 0, Math.PI * 2);
            ctx.stroke();

            // Goal boxes
            const boxWidth = 120;
            const boxHeight = 200;
            ctx.strokeRect(20, (canvas.height - boxHeight) / 2, boxWidth, boxHeight);
            ctx.strokeRect(canvas.width - 20 - boxWidth, (canvas.height - boxHeight) / 2, boxWidth, boxHeight);
        }

        function getHeatColor(intensity) {
            // Blue -> Cyan -> Green -> Yellow -> Red
            const h = (1 - intensity) * 240;  // 240 (blue) to 0 (red)
            const s = 100;
            const l = 50;
            const a = Math.min(intensity * 1.5, 0.7);
            return `hsla(${h}, ${s}%, ${l}%, ${a})`;
        }

        // Initial load
        loadHeatmap();
    </script>
</body>
</html>
"""
