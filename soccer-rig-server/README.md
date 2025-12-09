# Soccer Rig Viewer Server

Web portal for viewing processed soccer recordings with natural language search, event timeline, and clip generation.

## Features

- **Viewer Portal** - End-user interface for parents, coaches, players, scouts
- **Team Code Auth** - Simple access control per team
- **Natural Language Search** - "Show me all saves by the goalkeeper"
- **Event Timeline** - Click to seek to goals, shots, saves, passes
- **Clip Generation** - Create and share short clips
- **Player Highlights** - Auto-generate highlight reels
- **Admin Dashboard** - Manage games, players, analytics

## Architecture

```
Processing Server ──► Viewer Server ──► End Users
                          │
                          ├── PostgreSQL (events, players)
                          ├── Video Storage
                          └── Flask + Nginx
```

## Installation

### Prerequisites

- Python 3.10+
- PostgreSQL
- FFmpeg
- Nginx (for production)

### Quick Setup

```bash
# Clone repository
git clone https://github.com/cmc0619/Traloxolcus-Claude.git
cd Traloxolcus-Claude/soccer-rig-server

# Create virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Setup PostgreSQL
sudo -u postgres psql << EOF
CREATE USER soccer_rig WITH PASSWORD 'your-password';
CREATE DATABASE soccer_rig OWNER soccer_rig;
EOF

# Configure
mkdir -p ~/.config/soccer-rig
cat > ~/.config/soccer-rig/server.yaml << EOF
server:
  host: "127.0.0.1"
  port: 5000

storage:
  base_path: "/var/soccer-rig/videos"

database:
  url: "postgresql://soccer_rig:your-password@localhost/soccer_rig"
EOF

# Initialize database
python -m soccer_server.app --init-db

# Run
python -m soccer_server.app
```

### Production Setup

See [DEPLOYMENT.md](../DEPLOYMENT.md) for full nginx + systemd setup.

## Usage

### Viewer Portal

Access at `http://your-server/watch`

1. Enter team code (e.g., `TIGERS24`)
2. Select a game from the list
3. Watch the panoramic video
4. Use natural language search
5. Click events to jump to timestamps
6. Create and share clips

### Admin Dashboard

Access at `http://your-server/admin`

- View all games and recordings
- Manage team codes
- View analytics and heatmaps
- Trigger reprocessing

## API Reference

### Authentication

```bash
# Validate team code
curl "http://server/api/v1/viewer/auth?code=TIGERS24"
```

### Games & Sessions

```bash
# List games for viewer
curl http://server/api/v1/viewer/games

# Get session details
curl http://server/api/v1/sessions/GAME_20240315_140000

# Stream video (supports Range requests)
curl http://server/api/v1/sessions/GAME_ID/stream/stitched
```

### Natural Language Query

```bash
# Search events
curl -X POST http://server/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "show me all saves by the goalkeeper", "game_id": 1}'
```

**Example queries:**
- "show me all goals"
- "saves by goalkeeper"
- "shots in the second half"
- "player 7 highlights"
- "corners and free kicks"

### Events

```bash
# Get all events for a game
curl http://server/api/v1/games/1/events

# Filter by type
curl "http://server/api/v1/games/1/events?type=save"

# Goalkeeper events only
curl http://server/api/v1/games/1/gk-events
```

### Clips

```bash
# Generate clip around timestamp
curl -X POST http://server/api/v1/clips/generate \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "GAME_20240315_140000",
    "timestamp": 1234.5,
    "duration_before": 5,
    "duration_after": 5
  }'

# Generate player highlight reel
curl -X POST http://server/api/v1/clips/player-highlight \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "GAME_20240315_140000",
    "player_id": 1,
    "max_duration": 120
  }'
```

### Processing Server Upload

These endpoints receive processed content from the GPU processing server:

```bash
# Initialize chunked upload
POST /api/v1/upload/init

# Upload chunk
POST /api/v1/upload/chunk

# Finalize upload
POST /api/v1/upload/finalize

# Mark session ready (imports events to DB)
POST /api/v1/sessions/<id>/ready
```

## Database Schema

### Games
- `id`, `session_id`, `title`, `date`, `duration_sec`
- `home_team`, `away_team`, `score`

### Players
- `id`, `game_id`, `name`, `jersey_number`
- `team`, `position`, `is_goalkeeper`

### Events
- `id`, `game_id`, `player_id`
- `event_type` (goal, shot, save, pass, dribble, etc.)
- `timestamp_sec`, `confidence`
- `x`, `y` (field coordinates)

## Event Types

| Type | Description |
|------|-------------|
| `goal` | Goal scored |
| `shot` | Shot attempt |
| `shot_on_target` | Shot on goal |
| `save` | Goalkeeper save |
| `pass` | Completed pass |
| `cross` | Cross into box |
| `corner` | Corner kick |
| `free_kick` | Free kick |
| `dribble` | Dribbling run |
| `tackle` | Tackle attempt |
| `punch` | GK punch |
| `catch` | GK catch |
| `distribution` | GK distribution |

## Configuration

```yaml
server:
  host: "127.0.0.1"
  port: 5000
  debug: false
  upload_max_size_gb: 50

storage:
  base_path: "/var/soccer-rig/videos"
  clips_path: "/var/soccer-rig/clips"
  max_storage_gb: 1000

database:
  url: "postgresql://user:pass@localhost/soccer_rig"

analytics:
  enabled: true
  detection_fps: 10
```

## Team Codes

Add team codes in the API or database:

```python
# In api/__init__.py
_team_codes = {
    "TIGERS24": {"name": "Tigers FC U14", "team_id": 1},
    "EAGLES24": {"name": "Eagles SC", "team_id": 2},
}
```

## File Structure

```
soccer-rig-server/
├── src/soccer_server/
│   ├── app.py           # Main Flask app
│   ├── api/             # REST API endpoints
│   ├── database/        # SQLAlchemy models
│   ├── storage/         # File storage management
│   ├── analytics/       # Video analysis pipeline
│   ├── query/           # Natural language query
│   └── config.py        # Configuration
├── web/static/
│   ├── index.html       # Admin dashboard
│   ├── watch.html       # Viewer portal
│   ├── css/
│   └── js/
└── requirements.txt
```

## License

MIT License
