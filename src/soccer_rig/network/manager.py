"""
Network manager for Soccer Rig.

Handles:
- WiFi mesh connection
- Access Point fallback mode
- Peer discovery via mDNS/Zeroconf
"""

import socket
import subprocess
import threading
import logging
import time
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# Try to import network libraries
try:
    import netifaces
    NETIFACES_AVAILABLE = True
except ImportError:
    NETIFACES_AVAILABLE = False

try:
    from zeroconf import ServiceBrowser, Zeroconf, ServiceInfo
    ZEROCONF_AVAILABLE = True
except ImportError:
    ZEROCONF_AVAILABLE = False


class NetworkManager:
    """
    Network connection and peer discovery manager.

    Features:
    - WiFi mesh connection management
    - Automatic AP fallback when mesh unavailable
    - mDNS-based peer discovery
    - Network status monitoring
    """

    SERVICE_TYPE = "_soccerrig._tcp.local."

    def __init__(self, config):
        """
        Initialize network manager.

        Args:
            config: Configuration with network settings
        """
        self.config = config
        self._ap_mode = False
        self._connected = False
        self._current_ssid: Optional[str] = None
        self._ip_address: Optional[str] = None
        self._peers: Dict[str, Dict] = {}
        self._lock = threading.Lock()

        # Zeroconf for peer discovery
        self._zeroconf: Optional[Zeroconf] = None
        self._service_browser = None

        # Start network monitoring
        self._start_monitoring()

        # Register this node for discovery
        self._register_service()

    def _start_monitoring(self) -> None:
        """Start background network monitoring."""
        def monitor_loop():
            while True:
                try:
                    self._update_network_status()
                    self._check_connectivity()
                except Exception as e:
                    logger.error(f"Network monitoring error: {e}")
                time.sleep(10)

        thread = threading.Thread(target=monitor_loop, daemon=True)
        thread.start()
        logger.info("Network monitoring started")

    def _update_network_status(self) -> None:
        """Update current network status."""
        with self._lock:
            # Get IP address
            self._ip_address = self._get_ip_address()

            # Get current SSID
            self._current_ssid = self._get_current_ssid()

            # Check if connected
            self._connected = self._ip_address is not None

    def _get_ip_address(self) -> Optional[str]:
        """Get current IP address."""
        if NETIFACES_AVAILABLE:
            try:
                # Try wlan0 first, then eth0
                for iface in ["wlan0", "eth0", "en0"]:
                    if iface in netifaces.interfaces():
                        addrs = netifaces.ifaddresses(iface)
                        if netifaces.AF_INET in addrs:
                            return addrs[netifaces.AF_INET][0]["addr"]
            except Exception:
                pass

        # Fallback method
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return None

    def _get_current_ssid(self) -> Optional[str]:
        """Get currently connected WiFi SSID."""
        try:
            result = subprocess.run(
                ["iwgetid", "-r"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip() or None
        except Exception:
            pass
        return None

    def _check_connectivity(self) -> None:
        """Check network connectivity and trigger AP fallback if needed."""
        if not self._connected and self.config.network.ap_fallback_enabled:
            if not self._ap_mode:
                logger.warning("No network connection, considering AP fallback")
                # Wait for configured timeout before switching to AP mode
                time.sleep(self.config.network.ap_fallback_timeout_sec)

                # Check again
                self._update_network_status()
                if not self._connected:
                    logger.info("Enabling AP fallback mode")
                    self.enable_ap_mode()

    def get_status(self) -> Dict[str, Any]:
        """Get current network status."""
        with self._lock:
            return {
                "connected": self._connected,
                "ap_mode": self._ap_mode,
                "ssid": self._current_ssid,
                "ip_address": self._ip_address,
                "hostname": socket.gethostname(),
                "peers_count": len(self._peers),
                "ap_ssid": self._get_ap_ssid() if self._ap_mode else None,
            }

    def _get_ap_ssid(self) -> str:
        """Get AP mode SSID for this node."""
        camera_id = self.config.camera.id
        suffix = camera_id.split("_")[-1] if "_" in camera_id else camera_id
        return f"{self.config.network.ap_ssid_prefix}{suffix}"

    def enable_ap_mode(self) -> Dict[str, Any]:
        """
        Enable Access Point mode.

        Creates a WiFi access point for direct connection.
        """
        if self._ap_mode:
            return {
                "success": True,
                "message": "Already in AP mode",
            }

        try:
            ap_ssid = self._get_ap_ssid()
            ap_password = self.config.network.ap_password

            # Create hostapd configuration
            hostapd_config = f"""
interface=wlan0
driver=nl80211
ssid={ap_ssid}
hw_mode=g
channel=7
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase={ap_password}
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
"""

            # Write hostapd config
            config_path = Path("/etc/hostapd/hostapd.conf")
            config_path.parent.mkdir(parents=True, exist_ok=True)

            with open(config_path, "w") as f:
                f.write(hostapd_config)

            # Configure static IP for AP mode
            dnsmasq_config = f"""
interface=wlan0
dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h
address=/soccer-rig.local/192.168.4.1
"""

            with open("/etc/dnsmasq.conf", "w") as f:
                f.write(dnsmasq_config)

            # Stop wpa_supplicant
            subprocess.run(
                ["sudo", "systemctl", "stop", "wpa_supplicant"],
                capture_output=True
            )

            # Configure interface
            subprocess.run([
                "sudo", "ip", "addr", "flush", "dev", "wlan0"
            ], capture_output=True)

            subprocess.run([
                "sudo", "ip", "addr", "add", "192.168.4.1/24", "dev", "wlan0"
            ], capture_output=True)

            subprocess.run([
                "sudo", "ip", "link", "set", "wlan0", "up"
            ], capture_output=True)

            # Start hostapd and dnsmasq
            subprocess.run(
                ["sudo", "systemctl", "start", "hostapd"],
                capture_output=True
            )
            subprocess.run(
                ["sudo", "systemctl", "start", "dnsmasq"],
                capture_output=True
            )

            self._ap_mode = True
            self._ip_address = "192.168.4.1"

            logger.info(f"AP mode enabled: {ap_ssid}")

            return {
                "success": True,
                "message": f"AP mode enabled",
                "ssid": ap_ssid,
                "ip_address": "192.168.4.1",
            }

        except Exception as e:
            logger.error(f"Error enabling AP mode: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    def disable_ap_mode(self) -> Dict[str, Any]:
        """
        Disable Access Point mode and reconnect to mesh.
        """
        if not self._ap_mode:
            return {
                "success": True,
                "message": "Not in AP mode",
            }

        try:
            # Stop AP services
            subprocess.run(
                ["sudo", "systemctl", "stop", "hostapd"],
                capture_output=True
            )
            subprocess.run(
                ["sudo", "systemctl", "stop", "dnsmasq"],
                capture_output=True
            )

            # Restart wpa_supplicant
            subprocess.run(
                ["sudo", "systemctl", "start", "wpa_supplicant"],
                capture_output=True
            )

            # Restart networking
            subprocess.run(
                ["sudo", "systemctl", "restart", "dhcpcd"],
                capture_output=True
            )

            self._ap_mode = False

            # Wait for connection
            time.sleep(5)
            self._update_network_status()

            logger.info("AP mode disabled, reconnecting to mesh")

            return {
                "success": True,
                "message": "AP mode disabled",
                "connected": self._connected,
                "ssid": self._current_ssid,
            }

        except Exception as e:
            logger.error(f"Error disabling AP mode: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    def _register_service(self) -> None:
        """Register this node for mDNS discovery."""
        if not ZEROCONF_AVAILABLE:
            logger.warning("Zeroconf not available, peer discovery disabled")
            return

        try:
            self._zeroconf = Zeroconf()

            # Create service info
            camera_id = self.config.camera.id
            port = self.config.network.web_port

            service_info = ServiceInfo(
                self.SERVICE_TYPE,
                f"{camera_id}.{self.SERVICE_TYPE}",
                port=port,
                properties={
                    "camera_id": camera_id,
                    "position": self.config.camera.position,
                    "version": "1.0.0",
                },
                server=f"{camera_id}.local.",
            )

            # Wait for IP to be available
            def register_when_ready():
                for _ in range(30):  # Wait up to 30 seconds
                    if self._ip_address:
                        try:
                            # Update service with current IP
                            addresses = [socket.inet_aton(self._ip_address)]
                            service_info = ServiceInfo(
                                self.SERVICE_TYPE,
                                f"{camera_id}.{self.SERVICE_TYPE}",
                                port=port,
                                addresses=addresses,
                                properties={
                                    "camera_id": camera_id,
                                    "position": self.config.camera.position,
                                    "version": "1.0.0",
                                },
                                server=f"{camera_id}.local.",
                            )
                            self._zeroconf.register_service(service_info)
                            logger.info(f"Registered mDNS service: {camera_id}")
                            break
                        except Exception as e:
                            logger.error(f"Error registering service: {e}")
                    time.sleep(1)

            thread = threading.Thread(target=register_when_ready, daemon=True)
            thread.start()

            # Start peer discovery
            self._start_peer_discovery()

        except Exception as e:
            logger.error(f"Error setting up mDNS: {e}")

    def _start_peer_discovery(self) -> None:
        """Start discovering peer nodes."""
        if not self._zeroconf:
            return

        class PeerListener:
            def __init__(self, manager):
                self.manager = manager

            def add_service(self, zc, type_, name):
                info = zc.get_service_info(type_, name)
                if info:
                    self.manager._add_peer(name, info)

            def remove_service(self, zc, type_, name):
                self.manager._remove_peer(name)

            def update_service(self, zc, type_, name):
                info = zc.get_service_info(type_, name)
                if info:
                    self.manager._add_peer(name, info)

        self._service_browser = ServiceBrowser(
            self._zeroconf,
            self.SERVICE_TYPE,
            PeerListener(self)
        )

    def _add_peer(self, name: str, info: ServiceInfo) -> None:
        """Add or update a discovered peer."""
        with self._lock:
            addresses = info.parsed_addresses()
            ip = addresses[0] if addresses else None

            properties = {}
            for key, value in info.properties.items():
                if isinstance(key, bytes):
                    key = key.decode()
                if isinstance(value, bytes):
                    value = value.decode()
                properties[key] = value

            self._peers[name] = {
                "name": name,
                "ip": ip,
                "port": info.port,
                "camera_id": properties.get("camera_id"),
                "position": properties.get("position"),
                "version": properties.get("version"),
                "last_seen": time.time(),
            }

            logger.info(f"Discovered peer: {properties.get('camera_id')} at {ip}")

    def _remove_peer(self, name: str) -> None:
        """Remove a peer that's no longer available."""
        with self._lock:
            if name in self._peers:
                logger.info(f"Peer removed: {name}")
                del self._peers[name]

    def get_peers(self) -> List[Dict[str, Any]]:
        """Get list of discovered peers."""
        with self._lock:
            return list(self._peers.values())

    def get_peer_by_id(self, camera_id: str) -> Optional[Dict[str, Any]]:
        """Get peer by camera ID."""
        with self._lock:
            for peer in self._peers.values():
                if peer.get("camera_id") == camera_id:
                    return peer
            return None

    def broadcast_to_peers(self, endpoint: str, data: Dict) -> Dict[str, Any]:
        """
        Send request to all peers.

        Args:
            endpoint: API endpoint to call
            data: Request data

        Returns:
            Dict with results from each peer
        """
        import requests

        results = {}
        peers = self.get_peers()

        for peer in peers:
            peer_id = peer.get("camera_id", "unknown")
            ip = peer.get("ip")
            port = peer.get("port", 8080)

            if not ip:
                continue

            try:
                url = f"http://{ip}:{port}/api/v1{endpoint}"
                response = requests.post(url, json=data, timeout=5)
                results[peer_id] = {
                    "success": response.ok,
                    "status_code": response.status_code,
                    "response": response.json() if response.ok else None,
                }
            except Exception as e:
                results[peer_id] = {
                    "success": False,
                    "error": str(e),
                }

        return results

    def cleanup(self) -> None:
        """Clean up network resources."""
        if self._zeroconf:
            try:
                self._zeroconf.close()
            except Exception:
                pass
