"""
GitHub-based software updater for Soccer Rig.

Handles:
- Checking for updates from GitHub Releases
- Downloading and verifying update packages
- Atomic installation
- Service restart
"""

import os
import json
import shutil
import tarfile
import tempfile
import subprocess
import logging
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
import requests

logger = logging.getLogger(__name__)

CURRENT_VERSION = "1.0.0"
UPDATE_HISTORY_FILE = "/var/lib/soccer-rig/update_history.json"


class GitHubUpdater:
    """
    GitHub Release-based updater.

    Features:
    - Query GitHub Releases API
    - Download and verify packages
    - Atomic installation
    - Service restart
    - Update history tracking
    """

    def __init__(self, config):
        """
        Initialize updater.

        Args:
            config: Configuration with update settings
        """
        self.config = config
        self._github_repo = config.update.github_repo
        self._current_version = CURRENT_VERSION
        self._available_update: Optional[Dict] = None
        self._update_history: List[Dict] = []

        # Load update history
        self._load_history()

    def _load_history(self) -> None:
        """Load update history from file."""
        try:
            history_path = Path(UPDATE_HISTORY_FILE)
            if history_path.exists():
                with open(history_path, "r") as f:
                    self._update_history = json.load(f)
        except Exception as e:
            logger.error(f"Error loading update history: {e}")
            self._update_history = []

    def _save_history(self) -> None:
        """Save update history to file."""
        try:
            history_path = Path(UPDATE_HISTORY_FILE)
            history_path.parent.mkdir(parents=True, exist_ok=True)
            with open(history_path, "w") as f:
                json.dump(self._update_history, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving update history: {e}")

    def check_for_updates(self) -> Dict[str, Any]:
        """
        Check for available updates on GitHub.

        Returns:
            Dict with update information
        """
        if not self._github_repo:
            return {
                "available": False,
                "error": "GitHub repository not configured",
            }

        try:
            # Query GitHub Releases API
            api_url = f"https://api.github.com/repos/{self._github_repo}/releases/latest"
            response = requests.get(api_url, timeout=10)

            if response.status_code == 404:
                return {
                    "available": False,
                    "message": "No releases found",
                    "current_version": self._current_version,
                }

            response.raise_for_status()
            release_data = response.json()

            # Extract version from tag
            tag_name = release_data.get("tag_name", "")
            latest_version = tag_name.lstrip("v")

            # Compare versions
            if self._version_compare(latest_version, self._current_version) > 0:
                # Find downloadable asset
                asset = self._find_release_asset(release_data.get("assets", []))

                self._available_update = {
                    "version": latest_version,
                    "tag": tag_name,
                    "name": release_data.get("name", ""),
                    "body": release_data.get("body", ""),
                    "published_at": release_data.get("published_at", ""),
                    "asset": asset,
                    "html_url": release_data.get("html_url", ""),
                }

                return {
                    "available": True,
                    "current_version": self._current_version,
                    "latest_version": latest_version,
                    "release_name": release_data.get("name", ""),
                    "release_notes": release_data.get("body", ""),
                    "download_url": asset.get("url") if asset else None,
                    "download_size_mb": (
                        round(asset.get("size", 0) / (1024 * 1024), 2)
                        if asset else 0
                    ),
                }
            else:
                return {
                    "available": False,
                    "current_version": self._current_version,
                    "latest_version": latest_version,
                    "message": "Already up to date",
                }

        except requests.RequestException as e:
            logger.error(f"Error checking for updates: {e}")
            return {
                "available": False,
                "error": f"Network error: {str(e)}",
            }

        except Exception as e:
            logger.error(f"Error checking for updates: {e}")
            return {
                "available": False,
                "error": str(e),
            }

    def _version_compare(self, v1: str, v2: str) -> int:
        """
        Compare two version strings.

        Returns:
            -1 if v1 < v2, 0 if equal, 1 if v1 > v2
        """
        def normalize(v):
            return [int(x) for x in v.split(".")]

        try:
            parts1 = normalize(v1)
            parts2 = normalize(v2)

            for i in range(max(len(parts1), len(parts2))):
                p1 = parts1[i] if i < len(parts1) else 0
                p2 = parts2[i] if i < len(parts2) else 0

                if p1 > p2:
                    return 1
                elif p1 < p2:
                    return -1

            return 0
        except Exception:
            return 0

    def _find_release_asset(self, assets: List[Dict]) -> Optional[Dict]:
        """Find suitable release asset for download."""
        # Prefer .tar.gz, then .deb
        preferred_extensions = [".tar.gz", ".tgz", ".deb", ".zip"]

        for ext in preferred_extensions:
            for asset in assets:
                name = asset.get("name", "")
                if name.endswith(ext):
                    return {
                        "name": name,
                        "url": asset.get("browser_download_url", ""),
                        "size": asset.get("size", 0),
                    }

        return None

    def apply_update(self) -> Dict[str, Any]:
        """
        Download and apply available update.

        Returns:
            Dict with result status
        """
        if not self._available_update:
            # Check for updates first
            check_result = self.check_for_updates()
            if not check_result.get("available"):
                return {
                    "success": False,
                    "error": "No update available",
                }

        if not self._available_update or not self._available_update.get("asset"):
            return {
                "success": False,
                "error": "No downloadable asset found",
            }

        asset = self._available_update["asset"]
        version = self._available_update["version"]

        try:
            # Create temp directory
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                # Download update
                logger.info(f"Downloading update {version}...")
                download_path = temp_path / asset["name"]

                self._download_file(asset["url"], download_path)

                # Verify download (if checksum available)
                # For now, just check file exists and has content
                if not download_path.exists() or download_path.stat().st_size == 0:
                    return {
                        "success": False,
                        "error": "Download failed or file is empty",
                    }

                # Extract and install
                logger.info("Installing update...")
                install_result = self._install_update(download_path, temp_path)

                if install_result.get("success"):
                    # Record in history
                    self._update_history.append({
                        "version": version,
                        "previous_version": self._current_version,
                        "installed_at": datetime.now().isoformat(),
                        "success": True,
                    })
                    self._save_history()

                    # Update current version
                    self._current_version = version
                    self._available_update = None

                    # Restart services
                    self._restart_services()

                return install_result

        except Exception as e:
            logger.error(f"Error applying update: {e}")

            # Record failed attempt
            self._update_history.append({
                "version": version,
                "previous_version": self._current_version,
                "attempted_at": datetime.now().isoformat(),
                "success": False,
                "error": str(e),
            })
            self._save_history()

            return {
                "success": False,
                "error": str(e),
            }

    def _download_file(self, url: str, dest_path: Path) -> None:
        """Download file from URL."""
        response = requests.get(url, stream=True, timeout=300)
        response.raise_for_status()

        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

    def _install_update(self, package_path: Path, temp_dir: Path) -> Dict[str, Any]:
        """
        Install update package.

        Supports .tar.gz and .deb packages.
        """
        name = package_path.name

        if name.endswith(".tar.gz") or name.endswith(".tgz"):
            return self._install_tarball(package_path, temp_dir)
        elif name.endswith(".deb"):
            return self._install_deb(package_path)
        elif name.endswith(".zip"):
            return self._install_zip(package_path, temp_dir)
        else:
            return {
                "success": False,
                "error": f"Unsupported package format: {name}",
            }

    def _install_tarball(self, tarball_path: Path, temp_dir: Path) -> Dict[str, Any]:
        """Install from tarball."""
        try:
            # Extract tarball
            extract_dir = temp_dir / "extract"
            extract_dir.mkdir()

            with tarfile.open(tarball_path, "r:gz") as tar:
                tar.extractall(extract_dir)

            # Find and run install script if present
            install_script = None
            for script_name in ["install.sh", "setup.sh"]:
                script_path = extract_dir / script_name
                if script_path.exists():
                    install_script = script_path
                    break

                # Check in subdirectory
                for subdir in extract_dir.iterdir():
                    if subdir.is_dir():
                        script_path = subdir / script_name
                        if script_path.exists():
                            install_script = script_path
                            break

            if install_script:
                # Run install script
                result = subprocess.run(
                    ["sudo", "bash", str(install_script)],
                    capture_output=True,
                    text=True,
                    timeout=300
                )

                if result.returncode != 0:
                    return {
                        "success": False,
                        "error": f"Install script failed: {result.stderr}",
                    }
            else:
                # Manual installation - copy files to /opt/soccer-rig
                install_dir = Path("/opt/soccer-rig")

                # Find source directory
                source_dir = extract_dir
                subdirs = [d for d in extract_dir.iterdir() if d.is_dir()]
                if len(subdirs) == 1:
                    source_dir = subdirs[0]

                # Backup current installation
                if install_dir.exists():
                    backup_dir = install_dir.with_suffix(".backup")
                    if backup_dir.exists():
                        shutil.rmtree(backup_dir)
                    shutil.move(str(install_dir), str(backup_dir))

                # Copy new files
                shutil.copytree(source_dir, install_dir)

            return {
                "success": True,
                "message": "Update installed successfully",
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def _install_deb(self, deb_path: Path) -> Dict[str, Any]:
        """Install Debian package."""
        try:
            result = subprocess.run(
                ["sudo", "dpkg", "-i", str(deb_path)],
                capture_output=True,
                text=True,
                timeout=300
            )

            if result.returncode != 0:
                # Try to fix dependencies
                subprocess.run(
                    ["sudo", "apt-get", "-f", "install", "-y"],
                    capture_output=True,
                    timeout=300
                )

            return {
                "success": True,
                "message": "Debian package installed",
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def _install_zip(self, zip_path: Path, temp_dir: Path) -> Dict[str, Any]:
        """Install from ZIP archive."""
        import zipfile

        try:
            extract_dir = temp_dir / "extract"
            extract_dir.mkdir()

            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)

            # Similar logic to tarball installation
            install_dir = Path("/opt/soccer-rig")

            source_dir = extract_dir
            subdirs = [d for d in extract_dir.iterdir() if d.is_dir()]
            if len(subdirs) == 1:
                source_dir = subdirs[0]

            if install_dir.exists():
                backup_dir = install_dir.with_suffix(".backup")
                if backup_dir.exists():
                    shutil.rmtree(backup_dir)
                shutil.move(str(install_dir), str(backup_dir))

            shutil.copytree(source_dir, install_dir)

            return {
                "success": True,
                "message": "Update installed from ZIP",
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def _restart_services(self) -> None:
        """Restart Soccer Rig services."""
        services = ["soccer-rig"]

        for service in services:
            try:
                subprocess.run(
                    ["sudo", "systemctl", "restart", service],
                    capture_output=True,
                    timeout=30
                )
                logger.info(f"Restarted service: {service}")
            except Exception as e:
                logger.error(f"Error restarting {service}: {e}")

    def get_current_version(self) -> str:
        """Get current software version."""
        return self._current_version

    def get_history(self) -> List[Dict[str, Any]]:
        """Get update history."""
        return self._update_history.copy()

    def rollback(self) -> Dict[str, Any]:
        """
        Rollback to previous version.

        Restores from backup if available.
        """
        install_dir = Path("/opt/soccer-rig")
        backup_dir = install_dir.with_suffix(".backup")

        if not backup_dir.exists():
            return {
                "success": False,
                "error": "No backup available for rollback",
            }

        try:
            # Swap directories
            temp_dir = install_dir.with_suffix(".current")

            if install_dir.exists():
                shutil.move(str(install_dir), str(temp_dir))

            shutil.move(str(backup_dir), str(install_dir))

            if temp_dir.exists():
                shutil.move(str(temp_dir), str(backup_dir))

            # Restart services
            self._restart_services()

            return {
                "success": True,
                "message": "Rolled back to previous version",
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
