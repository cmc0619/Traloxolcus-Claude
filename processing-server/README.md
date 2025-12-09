# Soccer Rig Processing Server

GPU-accelerated video processing server for stitching multi-camera recordings and running ML event detection.

## Overview

The processing server receives raw 4K recordings from Pi camera nodes, stitches them into a panoramic view, runs ML-based event detection, and pushes the processed content to a viewer server.

```
Pi Nodes ──► Processing Server (GPU) ──► Viewer Server
              │
              ├── Video Stitching (NVENC)
              ├── ML Event Detection (YOLO)
              └── Push to Viewer
```

## Features

- **GPU-Accelerated Stitching**: Combines 3 camera feeds into 5760x1080 panorama using FFmpeg + NVENC
- **ML Event Detection**: YOLO-based player/ball tracking with event classification
- **Event Types Detected**:
  - Goals, shots, shots on target
  - Saves, punches, catches (goalkeeper)
  - Passes, crosses, corners
  - Dribbles, tackles
- **Chunked Upload**: Receive large files from Pi nodes with resume support
- **Push Service**: Sync processed videos to viewer server via API, rsync, or S3

## Hardware Requirements

- NVIDIA GPU (GTX 1080+ or RTX series recommended)
- 32GB+ RAM
- Fast SSD (1TB+ recommended)
- CUDA 11.0+

## Installation

### 1. Install System Dependencies

```bash
# Ubuntu 22.04
sudo apt update
sudo apt install -y python3-pip python3-venv ffmpeg

# NVIDIA drivers and CUDA
sudo apt install -y nvidia-driver-535 nvidia-cuda-toolkit

# Verify GPU
nvidia-smi
```

### 2. Install Processing Server

```bash
git clone https://github.com/cmc0619/Traloxolcus-Claude.git
cd Traloxolcus-Claude/processing-server

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install with GPU support
pip install -e ".[gpu]"
```

### 3. Download ML Models

```bash
# Models download automatically on first run, or manually:
python -c "from ultralytics import YOLO; YOLO('yolov8x.pt'); YOLO('yolov8n.pt')"
```

### 4. Configure

```bash
# Create directories
sudo mkdir -p /var/soccer-rig/{incoming,processing,output}
sudo chown -R $USER:$USER /var/soccer-rig

# Copy and edit config
cp config/processing.example.yaml config/processing.yaml
nano config/processing.yaml
```

## Configuration

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
  codec: "h264_nvenc"  # or libx264 for CPU
  output_resolution: [5760, 1080]
  output_fps: 30
  output_bitrate_mbps: 35

ml:
  enabled: true
  use_gpu: true
  device: "cuda:0"
  player_model: "yolov8x.pt"
  ball_model: "yolov8n.pt"
  detection_fps: 10
  confidence_threshold: 0.5

push:
  enabled: true
  method: "api"  # api, rsync, or s3
  viewer_server_url: "https://your-viewer-server.com"
  api_key: "your-api-key"
```

## Running

### Development

```bash
source venv/bin/activate
python -m processing_server.app --config config/processing.yaml --debug
```

### Production (systemd)

```bash
sudo cp config/processing-server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable processing-server
sudo systemctl start processing-server
```

## API Reference

### Ingest Endpoints (from Pi nodes)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/upload/init` | POST | Initialize chunked upload |
| `/api/upload/chunk` | POST | Upload a chunk |
| `/api/upload/finalize` | POST | Finalize upload |
| `/api/session/<id>/manifest` | POST | Upload session manifest |
| `/api/session/<id>/status` | GET | Get session status |
| `/api/sessions` | GET | List all sessions |
| `/health` | GET | Health check |

### Example: Upload from Pi

```bash
# Initialize upload
curl -X POST http://processing-server:5100/api/upload/init \
  -H "Content-Type: application/json" \
  -d '{
    "node_id": "CAM_L",
    "session_id": "GAME_20240315_140000",
    "filename": "CAM_L.mp4",
    "file_size": 5000000000,
    "chunk_size": 104857600
  }'

# Upload chunks
curl -X POST http://processing-server:5100/api/upload/chunk \
  -F "upload_id=xxx" \
  -F "chunk_index=0" \
  -F "chunk=@chunk_000000"

# Finalize
curl -X POST http://processing-server:5100/api/upload/finalize \
  -H "Content-Type: application/json" \
  -d '{"upload_id": "xxx", "total_chunks": 50}'
```

## Processing Pipeline

When all 3 camera recordings are received:

1. **Stitch Videos** (~10-15 min for 90-min game)
   - Align cameras using calibration data
   - Blend overlapping regions
   - Encode with GPU (NVENC)

2. **ML Analysis** (~20-30 min)
   - Detect players and ball every 100ms
   - Track objects across frames
   - Classify events (goals, saves, passes, etc.)
   - Generate timestamps and metadata

3. **Push to Viewer** (~5-10 min depending on bandwidth)
   - Upload panorama video
   - Upload metadata JSON
   - Notify viewer server

## Event Detection

The ML pipeline detects these event types:

| Event | Description | Confidence |
|-------|-------------|------------|
| `goal` | Ball enters goal | High |
| `shot` | Fast ball toward goal | Medium |
| `save` | Goalkeeper blocks shot | Medium |
| `pass` | Ball transfer between players | Medium |
| `dribble` | Player maintains possession | Medium |
| `tackle` | Player wins ball | Low |

## Output Files

For each processed session:

```
/var/soccer-rig/output/GAME_20240315_140000/
├── GAME_20240315_140000_panorama.mp4   # Stitched video
├── GAME_20240315_140000_metadata.json  # Events + timestamps
├── GAME_20240315_140000_thumb.jpg      # Thumbnail
└── GAME_20240315_140000_events.json    # Raw ML output
```

## Troubleshooting

### GPU Not Detected

```bash
# Check NVIDIA driver
nvidia-smi

# Check CUDA
nvcc --version

# Check FFmpeg NVENC support
ffmpeg -encoders | grep nvenc
```

### Out of GPU Memory

Reduce batch size in config:

```yaml
ml:
  batch_size: 4  # Lower from 8
```

### Slow Processing

- Ensure GPU encoding is enabled (`h264_nvenc`)
- Check GPU utilization: `watch nvidia-smi`
- Consider reducing `detection_fps`

## License

MIT License
