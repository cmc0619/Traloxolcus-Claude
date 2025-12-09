# Soccer Rig System - Deployment Guide

Complete deployment guide for the Multi-Camera Soccer Recording System.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SOCCER FIELD                                    │
│                                                                              │
│   ┌──────────┐         ┌──────────┐         ┌──────────┐                   │
│   │  Pi 5    │         │  Pi 5    │         │  Pi 5    │                   │
│   │  CAM_L   │         │  CAM_C   │         │  CAM_R   │                   │
│   │  (Left)  │         │ (Center) │         │ (Right)  │                   │
│   └────┬─────┘         └────┬─────┘         └────┬─────┘                   │
│        │                    │                    │                          │
└────────┼────────────────────┼────────────────────┼──────────────────────────┘
         │                    │                    │
         │    WiFi/Ethernet   │                    │
         └────────────────────┼────────────────────┘
                              │
                              ▼
                   ┌─────────────────────┐
                   │  PROCESSING SERVER  │
                   │  (Home, GPU)        │
                   │                     │
                   │  • Receive uploads  │
                   │  • Stitch panorama  │
                   │  • ML detection     │
                   │  • Push to viewer   │
                   └──────────┬──────────┘
                              │
                              │  Internet
                              ▼
                   ┌─────────────────────┐
                   │   VIEWER SERVER     │
                   │   (VPS/Cloud)       │
                   │                     │
                   │  • Store videos     │
                   │  • Serve portal     │
                   │  • NL search        │
                   │  • Clip generation  │
                   └─────────────────────┘
                              │
                              ▼
                   ┌─────────────────────┐
                   │      END USERS      │
                   │                     │
                   │  Parents, Coaches,  │
                   │  Players, Scouts    │
                   └─────────────────────┘
```

---

## Part 1: Pi Camera Nodes

### Hardware Requirements (per node)
- Raspberry Pi 5 (4GB+ RAM recommended)
- Pi Camera Module 3 or HQ Camera
- 128GB+ microSD card (fast, A2 rated)
- USB-C power supply (5V 5A)
- Weatherproof enclosure
- Tripod or mounting pole

### Software Setup

```bash
# 1. Flash Raspberry Pi OS (64-bit, Lite recommended)
# Use Raspberry Pi Imager, enable SSH, set hostname

# 2. SSH into Pi
ssh pi@cam-left.local  # or cam-center, cam-right

# 3. Update system
sudo apt update && sudo apt upgrade -y

# 4. Install dependencies
sudo apt install -y python3-pip python3-venv libcamera-apps ffmpeg espeak-ng

# 5. Clone repository
git clone https://github.com/cmc0619/Traloxolcus-Claude.git
cd Traloxolcus-Claude

# 6. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 7. Install Pi node package
pip install -e .

# 8. Configure the node
mkdir -p ~/.config/soccer-rig
cat > ~/.config/soccer-rig/config.yaml << 'EOF'
camera:
  id: "CAM_L"  # CAM_L, CAM_C, or CAM_R
  resolution: [3840, 2160]  # 4K
  fps: 30

storage:
  recordings_path: "/home/pi/recordings"
  max_storage_gb: 100

offload:
  server_url: "http://192.168.1.100:5100"  # Processing server IP
  auto_offload: true
  delete_after_offload: false

audio:
  enabled: true
  voice: "en"
EOF

# 9. Test camera
libcamera-hello --timeout 5000

# 10. Create systemd service for auto-start
sudo cat > /etc/systemd/system/soccer-rig.service << 'EOF'
[Unit]
Description=Soccer Rig Camera Node
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/Traloxolcus-Claude
ExecStart=/home/pi/Traloxolcus-Claude/venv/bin/python -m soccer_rig.cli record --auto
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable soccer-rig
```

### Field Setup

1. Position cameras along sideline:
   - **CAM_L**: Left third of field
   - **CAM_C**: Center (midfield)
   - **CAM_R**: Right third of field

2. Run framing assistant on each Pi:
```bash
soccer-rig frame --camera CAM_L
# Follow audio prompts to align field in frame
```

3. Start recording:
```bash
# Manual start
soccer-rig record --session "GAME_$(date +%Y%m%d_%H%M%S)"

# Or use systemd service
sudo systemctl start soccer-rig
```

---

## Part 2: Processing Server (GPU)

### Hardware Requirements
- NVIDIA GPU (GTX 1080+ or RTX series recommended)
- 32GB+ RAM
- Fast SSD (1TB+ for video processing)
- Gigabit network connection

### Software Setup

```bash
# 1. Install NVIDIA drivers and CUDA
# Ubuntu 22.04:
sudo apt install -y nvidia-driver-535 nvidia-cuda-toolkit

# Verify GPU
nvidia-smi

# 2. Install system dependencies
sudo apt install -y python3-pip python3-venv ffmpeg

# 3. Clone repository
git clone https://github.com/cmc0619/Traloxolcus-Claude.git
cd Traloxolcus-Claude/processing-server

# 4. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 5. Install with GPU support
pip install -e ".[gpu]"

# 6. Download ML models (automatic on first run, or manual):
python -c "from ultralytics import YOLO; YOLO('yolov8x.pt'); YOLO('yolov8n.pt'); YOLO('yolov8x-pose.pt')"

# 7. Create directories
sudo mkdir -p /var/soccer-rig/{incoming,processing,output}
sudo chown -R $USER:$USER /var/soccer-rig

# 8. Configure
cp config/processing.example.yaml config/processing.yaml
nano config/processing.yaml
```

### Configuration (processing.yaml)

```yaml
server:
  host: "0.0.0.0"
  port: 5100

storage:
  incoming_path: "/var/soccer-rig/incoming"
  processing_path: "/var/soccer-rig/processing"
  output_path: "/var/soccer-rig/output"

stitcher:
  enabled: true
  use_gpu: true
  codec: "h264_nvenc"  # GPU encoding
  output_resolution: [5760, 1080]

ml:
  enabled: true
  use_gpu: true
  device: "cuda:0"
  player_model: "yolov8x.pt"
  detection_fps: 10

push:
  enabled: true
  method: "api"
  viewer_server_url: "https://your-domain.com"  # or http://your-server-ip for no SSL
  api_key: "your-secure-api-key"
```

### Run as Service

```bash
# Create systemd service
sudo cat > /etc/systemd/system/processing-server.service << 'EOF'
[Unit]
Description=Soccer Rig Processing Server
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/Traloxolcus-Claude/processing-server
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/processing-server --config config/processing.yaml
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable processing-server
sudo systemctl start processing-server

# Check logs
sudo journalctl -u processing-server -f
```

---

## Part 3: Viewer Server (VPS)

### Requirements
- VPS with 2+ CPU cores, 4GB+ RAM
- 500GB+ storage for videos
- Domain name (for SSL) or static IP

### Software Setup

```bash
# 1. Update system (Ubuntu 22.04)
sudo apt update && sudo apt upgrade -y

# 2. Install dependencies
sudo apt install -y python3-pip python3-venv ffmpeg nginx certbot python3-certbot-nginx postgresql

# 3. Setup PostgreSQL
sudo -u postgres psql << 'EOF'
CREATE USER soccer_rig WITH PASSWORD 'your-secure-password';
CREATE DATABASE soccer_rig OWNER soccer_rig;
EOF

# 4. Clone repository
git clone https://github.com/cmc0619/Traloxolcus-Claude.git
cd Traloxolcus-Claude/soccer-rig-server

# 5. Create virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 6. Create directories
sudo mkdir -p /var/soccer-rig/videos
sudo chown -R $USER:$USER /var/soccer-rig

# 7. Configure
mkdir -p ~/.config/soccer-rig
cat > ~/.config/soccer-rig/server.yaml << 'EOF'
server:
  host: "127.0.0.1"
  port: 5000
  debug: false

storage:
  base_path: "/var/soccer-rig/videos"

database:
  url: "postgresql://soccer_rig:your-secure-password@localhost/soccer_rig"

analytics:
  enabled: true
EOF

# 8. Initialize database
python -m soccer_server.app --init-db
```

### Nginx Configuration

```bash
sudo cat > /etc/nginx/sites-available/soccer-rig << 'EOF'
server {
    listen 80;
    server_name your-domain.com;

    client_max_body_size 50G;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    # Video streaming optimization
    location /api/v1/sessions/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_buffering off;
        proxy_request_buffering off;
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/soccer-rig /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default  # Remove default site
sudo nginx -t
sudo systemctl reload nginx

# SSL certificate (recommended for production)
sudo certbot --nginx -d your-domain.com
```

### Run as Service

```bash
sudo cat > /etc/systemd/system/soccer-server.service << 'EOF'
[Unit]
Description=Soccer Rig Viewer Server
After=network.target postgresql.service

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/Traloxolcus-Claude/soccer-rig-server
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/python -m soccer_server.app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable soccer-server
sudo systemctl start soccer-server
```

---

## Part 4: Network Configuration

### Option A: Local Network (Same Location)

```
Pi Nodes ──WiFi──> Processing Server (192.168.1.100)
                          │
                     Internet
                          │
                          ▼
                   Viewer Server (VPS)
```

Configure Pi nodes to upload to local processing server IP.

### Option B: Field Hotspot

For portable setups, use a mobile hotspot:

```bash
# On Processing Server (or dedicated router)
# Create WiFi hotspot named "SoccerRig"
# Pi nodes connect automatically
```

### Firewall Rules

```bash
# Processing Server
sudo ufw allow 5100/tcp  # Ingest from Pi nodes

# Viewer Server
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

---

## Part 5: Game Day Workflow

### Pre-Game (30 min before)

```bash
# 1. Power on all Pi nodes
# 2. Verify network connectivity
ssh pi@cam-left.local "ping -c 1 192.168.1.100"

# 3. Run framing check on each camera
soccer-rig frame --verify

# 4. Start recording on all nodes
# Option A: Manual
ssh pi@cam-left.local "soccer-rig record --session GAME_$(date +%Y%m%d)"
ssh pi@cam-center.local "soccer-rig record --session GAME_$(date +%Y%m%d)"
ssh pi@cam-right.local "soccer-rig record --session GAME_$(date +%Y%m%d)"

# Option B: Coordinated start (from any Pi)
soccer-rig broadcast start --session "GAME_$(date +%Y%m%d_%H%M%S)"
```

### During Game

- Recordings happen automatically
- Check status: `soccer-rig status`
- Audio feedback confirms recording

### Post-Game

```bash
# 1. Stop recording
soccer-rig broadcast stop

# 2. Offload to processing server (automatic if configured)
soccer-rig offload --session GAME_20240315_140000

# 3. Monitor processing
curl http://192.168.1.100:5100/api/sessions/GAME_20240315_140000/status

# 4. Once complete, video available at:
# http://your-server-ip/watch
```

---

## Part 6: User Access

### Team Code Setup

Add team codes in the viewer server config or database:

```python
# In soccer_server/api/__init__.py or database
_team_codes = {
    "TIGERS24": {"name": "Tigers FC U14", "team_id": 1},
    "EAGLES24": {"name": "Eagles SC", "team_id": 2},
}
```

### End User Instructions

1. Go to `http://your-server-ip/watch`
2. Enter team code (e.g., `TIGERS24`)
3. Select game from list
4. Features available:
   - Watch full game with panorama view
   - Search: "show me all saves by goalkeeper"
   - Click events to jump to timestamp
   - Create and share clips
   - Download player highlights

---

## Troubleshooting

### Pi Nodes
```bash
# Check camera
libcamera-hello --list-cameras

# Check disk space
df -h

# Check service
sudo systemctl status soccer-rig
sudo journalctl -u soccer-rig -f
```

### Processing Server
```bash
# Check GPU
nvidia-smi

# Check service
sudo systemctl status processing-server
sudo journalctl -u processing-server -f

# Test FFmpeg with NVENC
ffmpeg -encoders | grep nvenc
```

### Viewer Server
```bash
# Check service
sudo systemctl status soccer-server

# Check database
sudo -u postgres psql -d soccer_rig -c "SELECT COUNT(*) FROM games;"

# Check nginx
sudo nginx -t
sudo tail -f /var/log/nginx/error.log
```

---

## Maintenance

### Storage Cleanup

```bash
# Processing server - remove old raw files
find /var/soccer-rig/incoming -mtime +7 -delete

# Viewer server - archive old sessions
# (implement based on retention policy)
```

### Backup

```bash
# Database
pg_dump soccer_rig > backup_$(date +%Y%m%d).sql

# Videos (to external storage)
rsync -av /var/soccer-rig/videos/ /mnt/backup/
```

---

## Quick Reference

| Component | Port | URL |
|-----------|------|-----|
| Pi Nodes | - | SSH: `pi@cam-*.local` |
| Processing Server | 5100 | `http://192.168.1.100:5100` |
| Viewer Server | 80/443 | `https://your-domain.com` |
| Viewer Portal | 80/443 | `https://your-domain.com/watch` |
| Admin Dashboard | 80/443 | `https://your-domain.com/admin` |
