# Soccer Rig - Multi-Camera Pi 5 Recording System

A three-camera synchronized 4K recording system for soccer matches using Raspberry Pi 5 nodes.

## Overview

This system consists of three independent Pi-Cam nodes (CAM_L, CAM_C, CAM_R) that:
- Capture synchronized 4K footage at 30fps using H.265 codec
- Serve a phone-accessible UI via WiFi mesh
- Store video to NVMe storage
- Provide status, health, and framing assistance
- Export recordings for downstream stitching and ML processing

## Hardware Requirements (Per Node)

- Raspberry Pi 5 (8GB recommended)
- Arducam 64MP Autofocus (IMX686)
- NVMe SSD (512GB minimum)
- Pi 5 NVMe carrier
- Tripod + adjustable camera mount
- USB-C battery bank or field battery pack
- Small speaker/buzzer

## Installation

### 1. System Dependencies

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv python3-picamera2 \
    ffmpeg chrony libcap-dev python3-prctl
```

### 2. Install Soccer Rig

```bash
# Clone the repository
git clone https://github.com/YOUR_ORG/soccer-rig.git
cd soccer-rig

# Run installation script
sudo ./install.sh
```

### 3. Configure the Node

Edit `/etc/soccer-rig/config.yaml`:

```yaml
camera:
  id: CAM_C  # CAM_L, CAM_C, or CAM_R
  position: center  # left, center, or right

network:
  mesh_ssid: SOCCER_MESH
  mesh_password: your_secure_password
```

### 4. Start Services

```bash
sudo systemctl enable soccer-rig
sudo systemctl start soccer-rig
```

## Web UI

Access the web interface at `http://<pi-ip>:8080`

Features:
- Live camera preview
- Start/Stop recording (all nodes or individual)
- View recording status and health metrics
- Configure camera settings
- Download recordings
- System updates

## REST API

Base path: `/api/v1`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/status` | GET | Get node status |
| `/record/start` | POST | Start recording |
| `/record/stop` | POST | Stop recording |
| `/recordings` | GET | List recordings |
| `/recordings/confirm` | POST | Confirm offload |
| `/config` | GET/POST | Get/Set configuration |
| `/shutdown` | POST | Shutdown node |
| `/selftest` | POST | Run self-test |
| `/update/check` | POST | Check for updates |
| `/update/apply` | POST | Apply update |

## Field Deployment

```
        [Goal]
          |
  CAM_L --+-- CAM_C --+-- CAM_R
          |           |
     [Sideline]  [Sideline]
```

- CAM_L: Left sideline corner
- CAM_C: Midfield (NTP master)
- CAM_R: Right sideline corner
- Mount height: 6-12 ft
- Slight downward tilt with overlapping coverage

## Time Synchronization

CAM_C acts as the NTP master. CAM_L and CAM_R sync to CAM_C.
Maximum allowed drift: 5ms

## Recording Specifications

- Resolution: 3840x2160 (4K)
- Frame Rate: 30 fps
- Codec: H.265 (fallback: H.264)
- Bitrate: 25-35 Mbps
- Container: MP4
- Duration: 110+ minutes continuous

## License

MIT License - See LICENSE file for details

## Version

soccer-rig v1.0.0
