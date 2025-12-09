# Soccer Rig - Multi-Camera Recording & Analysis System

A complete system for recording, processing, and viewing soccer matches with AI-powered event detection.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           SOCCER FIELD                                   │
│                                                                          │
│     ┌─────────┐       ┌─────────┐       ┌─────────┐                    │
│     │  Pi 5   │       │  Pi 5   │       │  Pi 5   │                    │
│     │  CAM_L  │       │  CAM_C  │       │  CAM_R  │                    │
│     └────┬────┘       └────┬────┘       └────┬────┘                    │
└──────────┼─────────────────┼─────────────────┼──────────────────────────┘
           │                 │                 │
           └────────────┬────┴────┬────────────┘
                        │         │
                        ▼         ▼
              ┌─────────────────────────┐
              │   PROCESSING SERVER     │
              │   (Home, GPU)           │
              │                         │
              │   • Receive uploads     │
              │   • Stitch panorama     │
              │   • ML event detection  │
              │   • Push to viewer      │
              └───────────┬─────────────┘
                          │
                          ▼
              ┌─────────────────────────┐
              │    VIEWER SERVER        │
              │    (VPS/Cloud)          │
              │                         │
              │   • Video streaming     │
              │   • Natural language    │
              │     search              │
              │   • Clip generation     │
              │   • User portal         │
              └───────────┬─────────────┘
                          │
                          ▼
              ┌─────────────────────────┐
              │      END USERS          │
              │                         │
              │  Parents • Coaches      │
              │  Players • Scouts       │
              └─────────────────────────┘
```

## Components

| Component | Description | Location |
|-----------|-------------|----------|
| **Pi Camera Nodes** | 3x Raspberry Pi 5 with 4K cameras | `src/soccer_rig/` |
| **Processing Server** | GPU-accelerated stitching + ML | `processing-server/` |
| **Viewer Server** | Web portal for end users | `soccer-rig-server/` |

## Features

### Recording (Pi Nodes)
- 4K @ 30fps synchronized recording
- H.265 hardware encoding
- Auto field framing with audio feedback
- NTP time sync across cameras
- Auto-upload to processing server

### Processing (GPU Server)
- Panorama stitching (3 cameras → 5760x1080)
- YOLO-based player/ball detection
- Event detection: goals, saves, shots, passes, dribbles
- Goalkeeper-specific tracking

### Viewing (Web Portal)
- Team code authentication
- Natural language search ("show me all saves")
- Click-to-seek event timeline
- Clip creation and sharing
- Player highlight generation

## Quick Start

### 1. Pi Camera Nodes

```bash
# On each Raspberry Pi 5
git clone https://github.com/cmc0619/Traloxolcus-Claude.git
cd Traloxolcus-Claude
sudo ./install.sh

# Configure camera ID (CAM_L, CAM_C, or CAM_R)
sudo nano /etc/soccer-rig/config.yaml

# Start service
sudo systemctl enable soccer-rig
sudo systemctl start soccer-rig
```

### 2. Processing Server

```bash
# On GPU server (NVIDIA required)
cd Traloxolcus-Claude/processing-server
python3 -m venv venv && source venv/bin/activate
pip install -e ".[gpu]"

# Configure
cp config/processing.example.yaml config/processing.yaml
nano config/processing.yaml

# Run
python -m processing_server.app
```

### 3. Viewer Server

```bash
# On VPS/cloud server
cd Traloxolcus-Claude/soccer-rig-server
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Configure database
sudo -u postgres createdb soccer_rig

# Run
python -m soccer_server.app
```

## Documentation

- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Complete deployment guide
- **[QUICKSTART.md](QUICKSTART.md)** - Field operations guide
- **[PROTOCOL.md](PROTOCOL.md)** - API and data formats
- **[processing-server/README.md](processing-server/README.md)** - Processing server docs
- **[soccer-rig-server/README.md](soccer-rig-server/README.md)** - Viewer server docs

## Hardware Requirements

### Per Camera Node
- Raspberry Pi 5 (4GB+ RAM)
- Pi Camera Module 3 or HQ Camera
- 128GB+ microSD (A2 rated)
- USB-C power supply (5V 5A)

### Processing Server
- NVIDIA GPU (GTX 1080+ / RTX)
- 32GB+ RAM
- 1TB+ fast SSD
- CUDA 11.0+

### Viewer Server
- 2+ CPU cores
- 4GB+ RAM
- 500GB+ storage
- Domain name (for SSL)

## API Quick Reference

### Pi Node API (port 8080)
```bash
curl http://pi-ip:8080/api/v1/status
curl -X POST http://pi-ip:8080/api/v1/record/start
curl -X POST http://pi-ip:8080/api/v1/record/stop
```

### Processing Server API (port 5100)
```bash
curl http://server:5100/health
curl http://server:5100/api/sessions
curl http://server:5100/api/sessions/GAME_ID/status
```

### Viewer Server API (port 80/443)
```bash
curl https://viewer/api/v1/health
curl https://viewer/api/v1/viewer/games
curl -X POST https://viewer/api/v1/query -d '{"query": "show goals"}'
```

## Game Day Workflow

1. **Setup** (15 min before)
   - Position cameras along sideline
   - Power on, verify all 3 online
   - Run framing assistant

2. **Record**
   - Press record on dashboard
   - All cameras start synchronized

3. **After Game**
   - Stop recording
   - Videos auto-upload to processing server
   - Processing takes ~30-45 min

4. **View**
   - Access `https://your-server/watch`
   - Enter team code
   - Search, clip, share!

## License

MIT License - See [LICENSE](LICENSE) for details.

## Version

v1.0.0
