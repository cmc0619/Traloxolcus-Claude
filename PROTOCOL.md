# Soccer Rig Offload Protocol

This document describes the communication protocol between the Pi camera nodes and the central server for uploading recordings.

## Overview

The offload system transfers recorded video files from each Pi camera node to the central server. Each recording is accompanied by a manifest file containing metadata and a checksum for verification.

## Architecture

```
[CAM_L (Pi)]  ──┐
                │
[CAM_C (Pi)]  ──┼──► [Soccer Rig Server]
                │
[CAM_R (Pi)]  ──┘
```

## API Endpoints

### Upload Endpoint

**POST** `/api/v1/upload`

Upload a recording file with metadata.

**Request (multipart/form-data):**
- `file` - The video file (video/mp4)
- `session_id` - Session identifier (e.g., "GAME_20240315_140000")
- `camera_id` - Camera identifier (CAM_L, CAM_C, CAM_R)
- `checksum` - SHA-256 hash of the file
- `manifest` - JSON string of the manifest (optional)

**Response:**
```json
{
  "success": true,
  "recording_id": "GAME_20240315_140000_CAM_C",
  "file_size": 12345678,
  "checksum_verified": true
}
```

### Confirm Upload

**POST** `/api/v1/upload/confirm`

Verify the upload completed successfully.

**Request:**
```json
{
  "session_id": "GAME_20240315_140000",
  "camera_id": "CAM_C"
}
```

**Response:**
```json
{
  "success": true,
  "session_id": "GAME_20240315_140000",
  "camera_id": "CAM_C",
  "file_size": 12345678,
  "checksum_sha256": "abc123..."
}
```

### Health Check

**GET** `/api/v1/health`

Check server status.

**Response:**
```json
{
  "status": "healthy",
  "storage_free_gb": 500.0,
  "active_uploads": 0
}
```

## Manifest Format

Each recording has an associated manifest file (JSON) containing metadata about the recording.

### Manifest Structure

```json
{
  "version": "1.0",
  "recording": {
    "id": "GAME_20240315_140000_CAM_C",
    "session_id": "GAME_20240315_140000",
    "camera_id": "CAM_C",
    "position": "center"
  },
  "file": {
    "name": "GAME_20240315_140000_CAM_C.mp4",
    "size_bytes": 12345678,
    "container": "mp4",
    "codec": "h265"
  },
  "video": {
    "resolution": {
      "width": 3840,
      "height": 2160
    },
    "fps": 30,
    "bitrate_mbps": 30,
    "duration_sec": 5400.5
  },
  "timing": {
    "start_time": "2024-03-15T14:00:00.123456Z",
    "end_time": "2024-03-15T15:30:00.654321Z",
    "ntp_synced": true,
    "sync_offset_ms": 2.3
  },
  "checksum": {
    "algorithm": "sha256",
    "value": "abc123def456..."
  },
  "device": {
    "hostname": "soccer-rig-cam-c",
    "ip_address": "192.168.1.102",
    "software_version": "1.0.0"
  },
  "quality": {
    "dropped_frames": 0,
    "temperature_avg_c": 55.2,
    "temperature_max_c": 62.1
  }
}
```

### Manifest Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `version` | string | Yes | Manifest format version |
| `recording.id` | string | Yes | Unique recording identifier |
| `recording.session_id` | string | Yes | Session identifier |
| `recording.camera_id` | string | Yes | Camera identifier (CAM_L/CAM_C/CAM_R) |
| `recording.position` | string | Yes | Physical position (left/center/right) |
| `file.name` | string | Yes | Video file name |
| `file.size_bytes` | integer | Yes | File size in bytes |
| `file.container` | string | Yes | Container format (mp4) |
| `file.codec` | string | Yes | Video codec (h264/h265) |
| `video.resolution.width` | integer | Yes | Video width in pixels |
| `video.resolution.height` | integer | Yes | Video height in pixels |
| `video.fps` | integer | Yes | Frames per second |
| `video.bitrate_mbps` | integer | Yes | Target bitrate in Mbps |
| `video.duration_sec` | float | Yes | Duration in seconds |
| `timing.start_time` | string | Yes | ISO 8601 recording start time |
| `timing.end_time` | string | Yes | ISO 8601 recording end time |
| `timing.ntp_synced` | boolean | Yes | Whether time was NTP synchronized |
| `timing.sync_offset_ms` | float | No | Offset from NTP time in ms |
| `checksum.algorithm` | string | Yes | Hash algorithm used |
| `checksum.value` | string | Yes | Hash value (hex encoded) |
| `device.hostname` | string | No | Pi hostname |
| `device.ip_address` | string | No | Pi IP address |
| `device.software_version` | string | No | Software version |
| `quality.dropped_frames` | integer | No | Number of dropped frames |
| `quality.temperature_avg_c` | float | No | Average CPU temperature |
| `quality.temperature_max_c` | float | No | Maximum CPU temperature |

## Session ID Format

Session IDs follow this pattern:

```
{NAME}_{DATE}_{TIME}

Examples:
- GAME_20240315_140000  (auto-generated)
- JVvsRivals_Home       (custom)
```

When auto-generated:
- `GAME_` prefix
- `YYYYMMDD` date
- `HHMMSS` time (24-hour, from master clock)

## Recording ID Format

Recording IDs combine session and camera:

```
{SESSION_ID}_{CAMERA_ID}

Example: GAME_20240315_140000_CAM_C
```

## Storage Layout

### On Pi (Source)

```
/mnt/nvme/
├── recordings/
│   └── GAME_20240315_140000/
│       └── CAM_C/
│           └── GAME_20240315_140000_CAM_C.mp4
└── manifests/
    └── GAME_20240315_140000/
        └── CAM_C/
            └── GAME_20240315_140000_CAM_C.json
```

### On Server (Destination)

```
/data/soccer-rig/
├── sessions/
│   └── GAME_20240315_140000/
│       ├── CAM_L/
│       │   ├── recording.mp4
│       │   └── manifest.json
│       ├── CAM_C/
│       │   ├── recording.mp4
│       │   └── manifest.json
│       ├── CAM_R/
│       │   ├── recording.mp4
│       │   └── manifest.json
│       └── stitched/
│           └── panorama.mp4
└── processing/
    └── jobs.json
```

## Upload Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         UPLOAD FLOW                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Pi Node                              Server                        │
│  ────────                             ──────                        │
│                                                                     │
│  1. Calculate checksum                                              │
│     ─────────────────►                                              │
│                                                                     │
│  2. POST /api/v1/upload                                             │
│     (file + metadata)                                               │
│     ─────────────────────────────────►                              │
│                                                                     │
│                                       3. Receive file               │
│                                       4. Verify checksum            │
│     ◄─────────────────────────────────                              │
│     {success: true}                                                 │
│                                                                     │
│  5. POST /api/v1/upload/confirm                                     │
│     ─────────────────────────────────►                              │
│                                                                     │
│                                       6. Return server checksum     │
│     ◄─────────────────────────────────                              │
│     {checksum_sha256: "..."}                                        │
│                                                                     │
│  7. Compare checksums                                               │
│     If match: mark offloaded                                        │
│     If mismatch: retry upload                                       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Retry Logic

The offload client implements exponential backoff:

| Attempt | Delay |
|---------|-------|
| 1 | 0s (immediate) |
| 2 | 5s |
| 3 | 10s |
| 4 | 20s |
| 5 | 40s |

After 5 failed attempts, the upload is marked as failed.

**Retry conditions:**
- Network timeout
- Server error (5xx)
- Checksum mismatch
- Connection refused

**No retry on:**
- Client error (4xx)
- File not found
- Invalid manifest

## Configuration

### Pi Node (`config.yaml`)

```yaml
offload:
  server_url: "http://192.168.1.200:8081"
  auto_upload: false
  upload_on_record_stop: false
  retry_count: 5
  retry_delay_sec: 5
  chunk_size_kb: 1024
  verify_checksum: true
```

### Server (`config.yaml`)

```yaml
storage:
  sessions_path: "/data/soccer-rig/sessions"
  processing_path: "/data/soccer-rig/processing"
  temp_path: "/data/soccer-rig/temp"
  min_free_space_gb: 50.0

server:
  host: "0.0.0.0"
  port: 8081
  max_upload_size_gb: 50.0
  upload_timeout_sec: 3600

processing:
  ffmpeg_path: "/usr/bin/ffmpeg"
  output_codec: "h264"
  output_preset: "medium"
  stitch_overlap_px: 100
```

## Security Considerations

1. **Checksum Verification** - All uploads verified with SHA-256
2. **No Authentication** - Designed for trusted local network only
3. **Size Limits** - Server enforces maximum upload size
4. **File Types** - Only MP4 video files accepted

For production deployments with untrusted networks, consider adding:
- TLS encryption (HTTPS)
- API key authentication
- IP allowlisting
