# Soccer Rig Quick Start Guide

This guide walks you through setting up and operating the multi-camera soccer recording system.

## Hardware Requirements (Per Camera Node)

- Raspberry Pi 5 (8GB recommended)
- Arducam IMX686 camera module
- 256GB+ microSD card (high endurance)
- USB-C PD power supply (27W+)
- Weatherproof enclosure for outdoor use

## Initial Setup

### 1. Install on Each Pi

Clone the repository and run the installer:

```bash
git clone https://github.com/your-org/soccer-rig.git
cd soccer-rig
sudo ./install.sh
```

The installer will:
- Install all dependencies
- Configure the camera
- Set up networking
- Create systemd services
- Configure the camera ID (CAM_L, CAM_C, or CAM_R)

### 2. Configure Each Node

Edit `/etc/soccer_rig/config.yaml` on each Pi:

```yaml
camera:
  id: CAM_C          # CAM_L, CAM_C, or CAM_R
  position: center   # left, center, or right

sync:
  is_master: true    # Only true on CAM_C

network:
  # Pre-configure peer IPs if not using mDNS
  peers:
    - camera_id: CAM_L
      ip: 192.168.1.101
    - camera_id: CAM_R
      ip: 192.168.1.103
```

### 3. Start the Service

```bash
sudo systemctl enable soccer-rig
sudo systemctl start soccer-rig
```

## Network Setup

### Option A: Connect to Existing WiFi

All Pis connect to the same WiFi network. They'll discover each other via mDNS.

### Option B: Master as Access Point

Configure CAM_C as an access point:

1. Enable AP mode in settings
2. Other Pis connect to the CAM_C network
3. Network name: `SoccerRig` (password in config)

## Operating the System

### Before the Game

1. **Power on all cameras** - Wait 1-2 minutes for boot

2. **Open the dashboard** - On your phone/tablet, go to:
   - `http://192.168.1.102:8080` (CAM_C IP)
   - Or `http://soccer-rig-cam-c.local:8080`

3. **Check all cameras are online**
   - Summary bar shows "3/3" cameras
   - All three camera cards show green "Online" status

4. **Run pre-flight check**
   - Tap "Pre-flight Check" button
   - Verify all checks pass:
     - All cameras detected
     - Time sync OK (< 5ms offset)
     - Storage sufficient (90+ minutes)
     - Temperature OK (< 75°C)

5. **Position cameras**
   - View live previews on each camera card
   - Adjust tripods until field is fully visible
   - CAM_L covers left third, CAM_C covers center, CAM_R covers right third

### Starting Recording

1. **Enter session name** (optional)
   - Default: `GAME_20240315_140000`
   - Or enter custom: `JVvsRivals_Home`

2. **Press the big red record button**
   - All cameras start simultaneously
   - Button turns red with stop icon
   - Timer shows elapsed time

3. **Verify recording started**
   - All camera cards show "Recording" status
   - Blinking red indicators

### During the Game

- Check dashboard periodically
- Watch for:
  - Storage warnings (< 10GB)
  - Temperature warnings (> 70°C)
  - Any camera going offline

### Stopping Recording

1. **Press the stop button** (formerly record button)
2. **Confirm stop** when prompted
3. All cameras stop and finalize video files

### After the Game

1. **Review recordings**
   - Tap "Recordings" button
   - Shows files from all cameras
   - Filter by camera if needed

2. **Download videos**
   - Click "Download" on each recording
   - Or connect to each Pi via USB/network

3. **Cleanup storage** (optional)
   - After confirming offload, tap "Delete Offloaded"
   - Frees space for next game

4. **Shutdown**
   - Settings > Shutdown All
   - Or leave running for next game

## Troubleshooting

### Camera Not Detected

- Check ribbon cable connection
- Reboot the Pi
- Verify camera is enabled: `sudo raspi-config`

### Cameras Not Discovering Each Other

- Verify all on same network
- Check firewall (port 8080)
- Manually add peers in Settings > Manage Peers

### Time Sync Issues

- Tap "Sync Time" button
- Wait 30 seconds
- Run pre-flight check again
- If CAM_C (master) has bad time, connect to internet

### Recording Failed to Start

- Check storage space
- Run test recording first
- Check camera status
- Review logs: Settings > (dev mode) > Logs

### Video Files Corrupted

- Ensure proper shutdown
- Don't remove power during recording
- Check SD card health

## API Quick Reference

```bash
# Get status
curl http://192.168.1.102:8080/api/v1/coordinator/status

# Start all cameras
curl -X POST http://192.168.1.102:8080/api/v1/coordinator/start

# Stop all cameras
curl -X POST http://192.168.1.102:8080/api/v1/coordinator/stop

# Run pre-flight check
curl -X POST http://192.168.1.102:8080/api/v1/coordinator/preflight
```

## LED/Audio Feedback

| Event | Feedback |
|-------|----------|
| Boot complete | Two beeps |
| Recording started | Single high beep |
| Recording stopped | Single low beep |
| Error | Three rapid beeps |
| Low storage | Periodic beep |

## Tips for Best Results

1. **Arrive 15 minutes early** - Time for setup and pre-flight
2. **Bring backup power** - Battery packs for extended games
3. **Check weather** - Protect from rain/extreme heat
4. **Test before game day** - Do a dry run with test recording
5. **Label your cameras** - Know which is L, C, R
