"""
Time synchronization manager.

Handles NTP/Chrony-based time sync between nodes.
CAM_C acts as master, CAM_L and CAM_R sync to it.
"""

import subprocess
import logging
import threading
import time
import re
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class SyncManager:
    """
    Manages time synchronization between camera nodes.

    Features:
    - Chrony-based NTP sync
    - Master/client configuration
    - Offset monitoring
    - Sync confidence reporting
    """

    def __init__(self, config):
        """
        Initialize sync manager.

        Args:
            config: Configuration with sync settings
        """
        self.config = config
        self._is_master = config.sync.is_master
        self._master_ip = config.sync.master_ip
        self._max_offset_ms = config.sync.max_offset_ms
        self._current_offset_ms: float = 0.0
        self._sync_confidence: str = "unknown"
        self._last_sync_time: Optional[datetime] = None
        self._lock = threading.Lock()

        # Start monitoring thread
        self._start_monitoring()

    def _start_monitoring(self) -> None:
        """Start background sync monitoring."""
        def monitor_loop():
            while True:
                try:
                    self._update_sync_status()
                except Exception as e:
                    logger.error(f"Sync monitoring error: {e}")
                time.sleep(self.config.sync.sync_check_interval_sec)

        thread = threading.Thread(target=monitor_loop, daemon=True)
        thread.start()
        logger.info("Sync monitoring started")

    def _update_sync_status(self) -> None:
        """Update current sync status from chrony."""
        with self._lock:
            try:
                # Get chrony tracking info
                result = subprocess.run(
                    ["chronyc", "tracking"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )

                if result.returncode == 0:
                    self._parse_chrony_output(result.stdout)
                    self._last_sync_time = datetime.now()
                else:
                    logger.warning(f"chronyc tracking failed: {result.stderr}")
                    self._sync_confidence = "error"

            except FileNotFoundError:
                # Chrony not installed - simulation mode
                self._current_offset_ms = 0.0
                self._sync_confidence = "simulated"
                self._last_sync_time = datetime.now()

            except subprocess.TimeoutExpired:
                logger.warning("chronyc command timed out")
                self._sync_confidence = "timeout"

            except Exception as e:
                logger.error(f"Error updating sync status: {e}")
                self._sync_confidence = "error"

    def _parse_chrony_output(self, output: str) -> None:
        """Parse chrony tracking output."""
        # Example output:
        # System time     : 0.000001234 seconds fast of NTP time
        # Last offset     : -0.000000123 seconds

        # Parse system time offset
        system_time_match = re.search(
            r"System time\s*:\s*([-\d.]+)\s*seconds\s*(fast|slow)",
            output
        )

        if system_time_match:
            offset_sec = float(system_time_match.group(1))
            direction = system_time_match.group(2)
            if direction == "slow":
                offset_sec = -offset_sec
            self._current_offset_ms = offset_sec * 1000

        # Parse last offset
        last_offset_match = re.search(
            r"Last offset\s*:\s*([-\d.e+]+)\s*seconds",
            output
        )

        if last_offset_match:
            last_offset_sec = float(last_offset_match.group(1))
            self._current_offset_ms = last_offset_sec * 1000

        # Determine sync confidence
        abs_offset = abs(self._current_offset_ms)
        if abs_offset < 1.0:
            self._sync_confidence = "excellent"
        elif abs_offset < self._max_offset_ms:
            self._sync_confidence = "good"
        elif abs_offset < self._max_offset_ms * 2:
            self._sync_confidence = "fair"
        else:
            self._sync_confidence = "poor"

    def get_status(self) -> Dict[str, Any]:
        """Get current sync status."""
        with self._lock:
            return {
                "is_master": self._is_master,
                "master_ip": self._master_ip if not self._is_master else None,
                "offset_ms": round(self._current_offset_ms, 3),
                "max_offset_ms": self._max_offset_ms,
                "within_tolerance": abs(self._current_offset_ms) <= self._max_offset_ms,
                "confidence": self._sync_confidence,
                "last_sync": (
                    self._last_sync_time.isoformat()
                    if self._last_sync_time else None
                ),
                "current_time": datetime.now().isoformat(),
            }

    def get_master_time(self) -> datetime:
        """
        Get current master time.

        For master node, returns local time.
        For client nodes, returns adjusted time based on offset.
        """
        now = datetime.now()

        if self._is_master:
            return now

        # Adjust for offset (offset is how far we are from master)
        # Positive offset = we're ahead, negative = we're behind
        offset_microseconds = int(self._current_offset_ms * 1000)
        from datetime import timedelta
        adjusted = now - timedelta(microseconds=offset_microseconds)

        return adjusted

    def force_sync(self) -> Dict[str, Any]:
        """Force immediate time synchronization."""
        try:
            # Burst mode sync
            result = subprocess.run(
                ["chronyc", "burst", "1/1"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                # Wait a moment then update status
                time.sleep(1)
                self._update_sync_status()

                return {
                    "success": True,
                    "message": "Sync triggered",
                    "status": self.get_status(),
                }
            else:
                return {
                    "success": False,
                    "error": result.stderr or "chronyc burst failed",
                }

        except FileNotFoundError:
            return {
                "success": False,
                "error": "chrony not installed",
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def configure_as_master(self) -> Dict[str, Any]:
        """Configure this node as NTP master."""
        try:
            chrony_config = """
# Soccer Rig NTP Master Configuration
server 0.pool.ntp.org iburst
server 1.pool.ntp.org iburst
server 2.pool.ntp.org iburst
server 3.pool.ntp.org iburst

# Allow local network to sync
allow 192.168.0.0/16
allow 10.0.0.0/8
allow 172.16.0.0/12

# Serve time even when not synced to external source
local stratum 10

driftfile /var/lib/chrony/drift
makestep 1.0 3
rtcsync
"""
            config_path = self.config.sync.chrony_config_path

            with open(config_path, "w") as f:
                f.write(chrony_config)

            # Restart chrony
            subprocess.run(["sudo", "systemctl", "restart", "chrony"], check=True)

            self._is_master = True
            logger.info("Configured as NTP master")

            return {
                "success": True,
                "message": "Configured as NTP master",
            }

        except Exception as e:
            logger.error(f"Error configuring as master: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    def configure_as_client(self, master_ip: str) -> Dict[str, Any]:
        """
        Configure this node as NTP client.

        Args:
            master_ip: IP address of the master node
        """
        try:
            chrony_config = f"""
# Soccer Rig NTP Client Configuration
# Sync to CAM_C master node
server {master_ip} iburst prefer

# Fallback to pool servers
pool pool.ntp.org iburst

driftfile /var/lib/chrony/drift
makestep 0.1 3
rtcsync
"""
            config_path = self.config.sync.chrony_config_path

            with open(config_path, "w") as f:
                f.write(chrony_config)

            # Restart chrony
            subprocess.run(["sudo", "systemctl", "restart", "chrony"], check=True)

            self._is_master = False
            self._master_ip = master_ip
            logger.info(f"Configured as NTP client, master: {master_ip}")

            return {
                "success": True,
                "message": f"Configured as NTP client, master: {master_ip}",
            }

        except Exception as e:
            logger.error(f"Error configuring as client: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    def get_sync_event_time(self) -> datetime:
        """
        Get synchronized time for sync event (beep).

        Returns the next second boundary for coordinated beeping.
        """
        now = self.get_master_time()

        # Round up to next second
        from datetime import timedelta
        next_second = now.replace(microsecond=0) + timedelta(seconds=1)

        return next_second

    def wait_for_sync_event(self, target_time: datetime) -> None:
        """
        Wait until the target synchronized time.

        Args:
            target_time: Target datetime to wait for
        """
        while True:
            now = self.get_master_time()
            delta = (target_time - now).total_seconds()

            if delta <= 0:
                break

            if delta > 0.1:
                time.sleep(0.05)
            else:
                # Busy wait for precision
                pass
