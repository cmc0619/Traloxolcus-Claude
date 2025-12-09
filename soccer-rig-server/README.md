# Soccer Rig Server

Central server for receiving, storing, and processing soccer game recordings from Pi camera nodes.

## Features

- **Upload Receiver**: Accept video uploads from Pi nodes via REST API
- **Checksum Verification**: Verify file integrity on upload
- **Session Management**: Organize recordings by game/session
- **Video Stitching**: Combine L/C/R cameras into panoramic view
- **Web Dashboard**: View all recordings, trigger processing
- **Storage Management**: Automatic cleanup, statistics

## Quick Start

### Prerequisites

- Python 3.10+
- FFmpeg (for video stitching)
- Redis (optional, for async processing)

### Installation

```bash
# Clone repository
git clone https://github.com/your-org/soccer-rig-server.git
cd soccer-rig-server

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create storage directories
sudo mkdir -p /var/lib/soccer-server/{recordings,temp}
sudo chown $USER:$USER /var/lib/soccer-server
```

### Running

```bash
# Development
python -m soccer_server.app --debug

# Production (with gunicorn)
gunicorn -w 4 -b 0.0.0.0:8000 "soccer_server.app:SoccerRigServer().app"
```

### Access

- Dashboard: http://localhost:8000
- API: http://localhost:8000/api/v1

## API Reference

### Upload Recording

```bash
curl -X POST http://localhost:8000/api/v1/upload \
  -F "file=@recording.mp4" \
  -F "session_id=GAME_20240315_140000" \
  -F "camera_id=CAM_L" \
  -F "checksum=abc123..." \
  -F "manifest={...}"
```

### List Sessions

```bash
curl http://localhost:8000/api/v1/sessions
```

### Get Session Details

```bash
curl http://localhost:8000/api/v1/sessions/GAME_20240315_140000
```

### Download Recording

```bash
curl -O http://localhost:8000/api/v1/sessions/GAME_20240315_140000/download/CAM_L
```

### Trigger Stitching

```bash
curl -X POST http://localhost:8000/api/v1/sessions/GAME_20240315_140000/stitch
```

### Storage Stats

```bash
curl http://localhost:8000/api/v1/stats
```

## Storage Structure

```
/var/lib/soccer-server/
├── recordings/
│   └── sessions/
│       └── GAME_20240315_140000/
│           ├── CAM_L.mp4
│           ├── CAM_L.json
│           ├── CAM_C.mp4
│           ├── CAM_C.json
│           ├── CAM_R.mp4
│           ├── CAM_R.json
│           ├── session.json
│           └── stitched.mp4
└── temp/
    └── (upload chunks)
```

## Video Stitching

The server can combine all three camera angles into a single panoramic view:

```
[CAM_L] [CAM_C] [CAM_R] → [Panorama 7680x2160]
```

Output:
- Resolution: 7680x2160 (8K wide)
- Codec: H.265 (configurable)
- Audio: From center camera

## Configuration

Edit `config/server.yaml`:

```yaml
storage:
  base_path: /var/lib/soccer-server/recordings
  max_storage_gb: 1000
  cleanup_after_days: 30

server:
  port: 8000

processing:
  stitch_enabled: true
  stitch_output_width: 7680
  stitch_output_height: 2160
```

## Integration with Pi Nodes

The server receives uploads from the soccer-rig Pi nodes. Configure Pi nodes with the server URL:

```yaml
# On Pi node: /etc/soccer-rig/config.yaml
offload:
  server_url: http://your-server:8000
  auto_upload: true
  delete_after_confirm: true
```

## License

MIT License
