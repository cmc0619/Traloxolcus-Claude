#!/bin/bash
#
# Soccer Rig Installation Script
# Installs the multi-camera recording system on Raspberry Pi 5
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}  Soccer Rig Installation${NC}"
echo -e "${GREEN}================================${NC}"
echo ""

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}This script must be run as root${NC}"
   echo "Please run: sudo ./install.sh"
   exit 1
fi

# Detect platform
PLATFORM=$(uname -m)
IS_PI=false
if [[ -f /proc/device-tree/model ]]; then
    MODEL=$(cat /proc/device-tree/model)
    if [[ $MODEL == *"Raspberry Pi"* ]]; then
        IS_PI=true
        echo -e "${GREEN}Detected: $MODEL${NC}"
    fi
fi

# Installation paths
INSTALL_DIR="/opt/soccer-rig"
CONFIG_DIR="/etc/soccer-rig"
DATA_DIR="/var/lib/soccer-rig"
LOG_DIR="/var/log/soccer_rig"
RECORDINGS_DIR="/mnt/nvme/recordings"
MANIFESTS_DIR="/mnt/nvme/manifests"

# Step 1: Install system dependencies
echo -e "\n${YELLOW}Step 1: Installing system dependencies...${NC}"
apt-get update
apt-get install -y \
    python3-pip \
    python3-venv \
    python3-dev \
    ffmpeg \
    chrony \
    hostapd \
    dnsmasq \
    libcap-dev \
    libasound2-dev \
    libavcodec-dev \
    libavformat-dev \
    libswscale-dev

# Install Pi-specific packages
if $IS_PI; then
    apt-get install -y \
        python3-picamera2 \
        python3-libcamera \
        libcamera-apps
fi

# Step 2: Create directories
echo -e "\n${YELLOW}Step 2: Creating directories...${NC}"
mkdir -p "$INSTALL_DIR"
mkdir -p "$CONFIG_DIR"
mkdir -p "$DATA_DIR"
mkdir -p "$LOG_DIR"
mkdir -p "$RECORDINGS_DIR"
mkdir -p "$MANIFESTS_DIR"

# Step 3: Copy files
echo -e "\n${YELLOW}Step 3: Copying files...${NC}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cp -r "$SCRIPT_DIR/src" "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR/web" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"

# Step 4: Create virtual environment
echo -e "\n${YELLOW}Step 4: Setting up Python environment...${NC}"
python3 -m venv "$INSTALL_DIR/venv"
source "$INSTALL_DIR/venv/bin/activate"

# Install Python dependencies
pip install --upgrade pip
pip install -r "$INSTALL_DIR/requirements.txt"

# On Pi, link system picamera2 to venv
if $IS_PI; then
    SITE_PACKAGES="$INSTALL_DIR/venv/lib/python3.*/site-packages"
    ln -sf /usr/lib/python3/dist-packages/picamera2 $SITE_PACKAGES/ 2>/dev/null || true
    ln -sf /usr/lib/python3/dist-packages/libcamera $SITE_PACKAGES/ 2>/dev/null || true
fi

deactivate

# Step 5: Create default configuration
echo -e "\n${YELLOW}Step 5: Creating configuration...${NC}"
if [[ ! -f "$CONFIG_DIR/config.yaml" ]]; then
    cat > "$CONFIG_DIR/config.yaml" << EOF
# Soccer Rig Configuration
# Edit this file to customize your camera node

camera:
  id: CAM_C  # Change to CAM_L, CAM_C, or CAM_R
  position: center  # Change to left, center, or right
  resolution_width: 3840
  resolution_height: 2160
  fps: 30
  codec: h265
  bitrate_mbps: 30
  container: mp4
  audio_enabled: false
  test_duration_sec: 10

network:
  mesh_ssid: SOCCER_MESH
  mesh_password: soccer_rig_2024
  ap_fallback_enabled: true
  ap_fallback_timeout_sec: 30
  ap_ssid_prefix: SOCCER_CAM_
  ap_password: soccercam123
  web_port: 8080

storage:
  recordings_path: /mnt/nvme/recordings
  manifests_path: /mnt/nvme/manifests
  min_free_space_gb: 10.0
  auto_delete_offloaded: true
  delete_after_confirm: false

sync:
  is_master: false  # Set to true for CAM_C
  master_ip: ""
  max_offset_ms: 5.0
  chrony_config_path: /etc/chrony/chrony.conf
  sync_check_interval_sec: 10

update:
  github_repo: ""
  check_on_boot: false
  auto_apply: false

audio:
  enabled: true
  volume: 80
  beep_on_record_start: true
  beep_on_record_stop: true
  beep_on_error: true
  beep_on_sync: true

production_mode: true
EOF
    echo -e "${GREEN}Created default configuration at $CONFIG_DIR/config.yaml${NC}"
else
    echo -e "${YELLOW}Configuration already exists, skipping...${NC}"
fi

# Step 6: Install systemd service
echo -e "\n${YELLOW}Step 6: Installing systemd service...${NC}"
cp "$SCRIPT_DIR/systemd/soccer-rig.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable soccer-rig

# Step 7: Configure NVMe mount (if not already mounted)
echo -e "\n${YELLOW}Step 7: Checking NVMe storage...${NC}"
if $IS_PI; then
    if ! mountpoint -q /mnt/nvme; then
        # Check for NVMe device
        if [[ -b /dev/nvme0n1p1 ]]; then
            echo "Mounting NVMe storage..."
            mount /dev/nvme0n1p1 /mnt/nvme || {
                echo -e "${YELLOW}Creating filesystem on NVMe...${NC}"
                mkfs.ext4 -L SOCCER_NVME /dev/nvme0n1p1
                mount /dev/nvme0n1p1 /mnt/nvme
            }

            # Add to fstab
            if ! grep -q "SOCCER_NVME" /etc/fstab; then
                echo "LABEL=SOCCER_NVME /mnt/nvme ext4 defaults,noatime 0 2" >> /etc/fstab
            fi
        elif [[ -b /dev/nvme0n1 ]]; then
            echo -e "${YELLOW}NVMe device found but not partitioned${NC}"
            echo "Please partition the NVMe drive and re-run installation"
        else
            echo -e "${YELLOW}No NVMe device found${NC}"
            echo "Using local storage instead"
            mkdir -p /mnt/nvme
        fi
    else
        echo "NVMe already mounted"
    fi
else
    echo "Not running on Pi, skipping NVMe setup"
    mkdir -p /mnt/nvme
fi

# Ensure recording directories exist with correct permissions
mkdir -p "$RECORDINGS_DIR" "$MANIFESTS_DIR"
chmod 755 "$RECORDINGS_DIR" "$MANIFESTS_DIR"

# Step 8: Configure Chrony for time sync
echo -e "\n${YELLOW}Step 8: Configuring time synchronization...${NC}"
if ! grep -q "Soccer Rig" /etc/chrony/chrony.conf; then
    cat >> /etc/chrony/chrony.conf << EOF

# Soccer Rig NTP Configuration
# Default: sync to pool.ntp.org
# For CAM_C (master): uncomment 'local' and 'allow' lines
# For CAM_L/CAM_R: set 'server' to CAM_C's IP

pool pool.ntp.org iburst
makestep 1.0 3
rtcsync

# Uncomment for CAM_C (master node):
# local stratum 10
# allow 192.168.0.0/16
# allow 10.0.0.0/8
EOF
    systemctl restart chrony
fi

# Step 9: Set up camera permissions
echo -e "\n${YELLOW}Step 9: Setting up camera permissions...${NC}"
if $IS_PI; then
    # Add video group access
    usermod -aG video root 2>/dev/null || true

    # Enable camera in boot config if needed
    if ! grep -q "camera_auto_detect=1" /boot/config.txt 2>/dev/null; then
        if ! grep -q "camera_auto_detect=1" /boot/firmware/config.txt 2>/dev/null; then
            CONFIG_FILE="/boot/config.txt"
            [[ -f /boot/firmware/config.txt ]] && CONFIG_FILE="/boot/firmware/config.txt"
            echo "camera_auto_detect=1" >> "$CONFIG_FILE"
            echo -e "${YELLOW}Camera enabled in $CONFIG_FILE${NC}"
        fi
    fi
fi

# Step 10: Create convenience scripts
echo -e "\n${YELLOW}Step 10: Creating convenience scripts...${NC}"
cat > /usr/local/bin/soccer-rig << 'EOF'
#!/bin/bash
# Soccer Rig CLI wrapper

case "$1" in
    start)
        systemctl start soccer-rig
        echo "Soccer Rig started"
        ;;
    stop)
        systemctl stop soccer-rig
        echo "Soccer Rig stopped"
        ;;
    restart)
        systemctl restart soccer-rig
        echo "Soccer Rig restarted"
        ;;
    status)
        systemctl status soccer-rig
        ;;
    logs)
        journalctl -u soccer-rig -f
        ;;
    config)
        ${EDITOR:-nano} /etc/soccer-rig/config.yaml
        ;;
    *)
        echo "Usage: soccer-rig {start|stop|restart|status|logs|config}"
        exit 1
        ;;
esac
EOF
chmod +x /usr/local/bin/soccer-rig

# Installation complete
echo ""
echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}  Installation Complete!${NC}"
echo -e "${GREEN}================================${NC}"
echo ""
echo "Next steps:"
echo "1. Edit configuration: sudo nano /etc/soccer-rig/config.yaml"
echo "   - Set camera.id (CAM_L, CAM_C, or CAM_R)"
echo "   - Set camera.position (left, center, right)"
echo "   - For CAM_C: set sync.is_master to true"
echo ""
echo "2. Start the service: sudo systemctl start soccer-rig"
echo ""
echo "3. Access the Web UI: http://$(hostname -I | awk '{print $1}'):8080"
echo ""
echo "Useful commands:"
echo "  soccer-rig start    - Start the service"
echo "  soccer-rig stop     - Stop the service"
echo "  soccer-rig status   - Check service status"
echo "  soccer-rig logs     - View live logs"
echo "  soccer-rig config   - Edit configuration"
echo ""

if $IS_PI; then
    echo -e "${YELLOW}Note: A reboot may be required for camera changes to take effect${NC}"
    echo "Run: sudo reboot"
fi
