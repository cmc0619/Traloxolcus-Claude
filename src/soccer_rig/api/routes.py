"""
REST API routes for Soccer Rig.

Base path: /api/v1
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path
from functools import wraps
from flask import Blueprint, request, jsonify, Response, current_app

logger = logging.getLogger(__name__)


def create_api_blueprint(app_context):
    """
    Create Flask blueprint with all API routes.

    Args:
        app_context: SoccerRigApp instance with all services

    Returns:
        Flask Blueprint
    """
    api = Blueprint("api", __name__, url_prefix="/api/v1")

    def get_recorder():
        return app_context.recorder

    def get_storage():
        return app_context.storage

    def get_sync():
        return app_context.sync

    def get_updater():
        return app_context.updater

    def get_config():
        return app_context.config

    def get_audio():
        return app_context.audio

    def get_network():
        return app_context.network

    def get_coordinator():
        return app_context.coordinator

    # =========================================================================
    # Coordinator Endpoints (Multi-Camera Control)
    # =========================================================================

    @api.route("/coordinator/status", methods=["GET"])
    def get_coordinator_status():
        """
        Get aggregated status from all cameras.

        Returns combined dashboard view with all camera statuses.
        """
        coordinator = get_coordinator()

        if not coordinator:
            return jsonify({"error": "Coordinator not available"}), 503

        return jsonify(coordinator.get_aggregated_status())

    @api.route("/coordinator/peers", methods=["GET"])
    def get_coordinator_peers():
        """Get list of all camera peers."""
        coordinator = get_coordinator()

        if not coordinator:
            return jsonify({"error": "Coordinator not available"}), 503

        return jsonify({"peers": coordinator.get_peers()})

    @api.route("/coordinator/peers", methods=["POST"])
    def add_coordinator_peer():
        """
        Manually add a peer camera.

        Request body:
        {
            "camera_id": "CAM_L",
            "ip": "192.168.1.100",
            "port": 8080
        }
        """
        coordinator = get_coordinator()

        if not coordinator:
            return jsonify({"error": "Coordinator not available"}), 503

        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body required"}), 400

        if "camera_id" not in data or "ip" not in data:
            return jsonify({"error": "camera_id and ip required"}), 400

        result = coordinator.add_peer(
            camera_id=data["camera_id"],
            ip=data["ip"],
            port=data.get("port", 8080),
            manual=True
        )

        return jsonify(result)

    @api.route("/coordinator/peers/<camera_id>", methods=["DELETE"])
    def remove_coordinator_peer(camera_id):
        """Remove a peer camera."""
        coordinator = get_coordinator()

        if not coordinator:
            return jsonify({"error": "Coordinator not available"}), 503

        result = coordinator.remove_peer(camera_id)
        return jsonify(result)

    @api.route("/coordinator/start", methods=["POST"])
    def coordinator_start_all():
        """
        Start recording on ALL cameras with synchronized timing.

        Request body (optional):
        {
            "session_id": "string"
        }
        """
        coordinator = get_coordinator()
        audio = get_audio()

        if not coordinator:
            return jsonify({"error": "Coordinator not available"}), 503

        data = request.get_json() or {}
        session_id = data.get("session_id")

        result = coordinator.start_all(session_id)

        if result.get("success") and audio:
            audio.beep_start()

        status_code = 200 if result.get("success") else 500
        return jsonify(result), status_code

    @api.route("/coordinator/stop", methods=["POST"])
    def coordinator_stop_all():
        """Stop recording on ALL cameras."""
        coordinator = get_coordinator()
        audio = get_audio()

        if not coordinator:
            return jsonify({"error": "Coordinator not available"}), 503

        result = coordinator.stop_all()

        if result.get("success") and audio:
            audio.beep_stop()

        status_code = 200 if result.get("success") else 500
        return jsonify(result), status_code

    @api.route("/coordinator/preflight", methods=["POST"])
    def coordinator_preflight():
        """
        Run pre-flight checks on all cameras.

        Verifies all systems ready for recording.
        """
        coordinator = get_coordinator()

        if not coordinator:
            return jsonify({"error": "Coordinator not available"}), 503

        result = coordinator.run_preflight_check()
        status_code = 200 if result.get("passed") else 500
        return jsonify(result), status_code

    @api.route("/coordinator/session", methods=["GET"])
    def get_current_session():
        """Get current recording session info."""
        coordinator = get_coordinator()

        if not coordinator:
            return jsonify({"error": "Coordinator not available"}), 503

        session = coordinator.get_current_session()
        if session:
            return jsonify(session)
        return jsonify({"session": None, "status": "idle"})

    @api.route("/coordinator/sessions", methods=["GET"])
    def get_session_history():
        """Get recording session history."""
        coordinator = get_coordinator()

        if not coordinator:
            return jsonify({"error": "Coordinator not available"}), 503

        return jsonify({"sessions": coordinator.get_session_history()})

    @api.route("/coordinator/recordings", methods=["GET"])
    def get_all_recordings():
        """Get recordings from all cameras."""
        coordinator = get_coordinator()

        if not coordinator:
            return jsonify({"error": "Coordinator not available"}), 503

        return jsonify(coordinator.get_all_recordings())

    @api.route("/coordinator/sync", methods=["POST"])
    def coordinator_sync_all():
        """Trigger time sync on all cameras."""
        coordinator = get_coordinator()

        if not coordinator:
            return jsonify({"error": "Coordinator not available"}), 503

        result = coordinator.trigger_sync_all()
        return jsonify(result)

    @api.route("/coordinator/test", methods=["POST"])
    def coordinator_test_all():
        """Run test recording on all cameras."""
        coordinator = get_coordinator()

        if not coordinator:
            return jsonify({"error": "Coordinator not available"}), 503

        result = coordinator.run_test_all()
        status_code = 200 if result.get("all_passed") else 500
        return jsonify(result), status_code

    # =========================================================================
    # Status Endpoints
    # =========================================================================

    @api.route("/status", methods=["GET"])
    def get_status():
        """
        Get comprehensive node status.

        Returns all status information including:
        - Camera status
        - Recording status
        - Storage status
        - Sync status
        - System health
        """
        recorder = get_recorder()
        storage = get_storage()
        sync = get_sync()
        config = get_config()

        try:
            camera_status = recorder.get_status() if recorder else {}
            storage_status = storage.get_status() if storage else {}
            sync_status = sync.get_status() if sync else {}

            return jsonify({
                "node": {
                    "camera_id": config.camera.id,
                    "camera_position": config.camera.position,
                    "version": "1.0.0",
                    "production_mode": config.production_mode,
                    "timestamp": datetime.now().isoformat(),
                },
                "camera": camera_status.get("camera", {}),
                "recording": camera_status.get("recording", {}),
                "storage": storage_status,
                "sync": sync_status,
                "system": _get_system_status(),
            })
        except Exception as e:
            logger.error(f"Error getting status: {e}")
            return jsonify({"error": str(e)}), 500

    @api.route("/health", methods=["GET"])
    def health_check():
        """Simple health check endpoint."""
        return jsonify({
            "status": "ok",
            "timestamp": datetime.now().isoformat()
        })

    # =========================================================================
    # Recording Endpoints
    # =========================================================================

    @api.route("/record/start", methods=["POST"])
    def start_recording():
        """
        Start video recording.

        Request body (optional):
        {
            "session_id": "string",
            "master_time": "ISO8601 timestamp"
        }
        """
        recorder = get_recorder()
        audio = get_audio()

        if not recorder:
            return jsonify({"error": "Recorder not available"}), 503

        data = request.get_json() or {}
        session_id = data.get(
            "session_id",
            f"SESSION_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        master_time_str = data.get("master_time")
        master_time = None

        if master_time_str:
            try:
                master_time = datetime.fromisoformat(master_time_str)
            except ValueError:
                return jsonify({"error": "Invalid master_time format"}), 400

        result = recorder.start_recording(session_id, master_time)

        if result.get("success"):
            if audio:
                audio.beep_start()
            return jsonify(result), 200
        else:
            return jsonify(result), 400

    @api.route("/record/stop", methods=["POST"])
    def stop_recording():
        """Stop video recording."""
        recorder = get_recorder()
        audio = get_audio()

        if not recorder:
            return jsonify({"error": "Recorder not available"}), 503

        result = recorder.stop_recording()

        if result.get("success"):
            if audio:
                audio.beep_stop()
            return jsonify(result), 200
        else:
            return jsonify(result), 400

    # =========================================================================
    # Recordings Management
    # =========================================================================

    @api.route("/recordings", methods=["GET"])
    def list_recordings():
        """
        List all recordings.

        Query params:
        - offloaded: true/false (filter by offload status)
        - session_id: filter by session
        """
        storage = get_storage()

        if not storage:
            return jsonify({"error": "Storage not available"}), 503

        offloaded = request.args.get("offloaded")
        session_id = request.args.get("session_id")

        filters = {}
        if offloaded is not None:
            filters["offloaded"] = offloaded.lower() == "true"
        if session_id:
            filters["session_id"] = session_id

        recordings = storage.list_recordings(filters)
        return jsonify({"recordings": recordings})

    @api.route("/recordings/<recording_id>", methods=["GET"])
    def get_recording(recording_id):
        """Get details of a specific recording."""
        storage = get_storage()

        if not storage:
            return jsonify({"error": "Storage not available"}), 503

        recording = storage.get_recording(recording_id)
        if recording:
            return jsonify(recording)
        return jsonify({"error": "Recording not found"}), 404

    @api.route("/recordings/confirm", methods=["POST"])
    def confirm_offload():
        """
        Confirm successful offload of a recording.

        Request body:
        {
            "session_id": "string",
            "camera_id": "string",
            "file": "filename",
            "checksum": {
                "algo": "sha256",
                "value": "hex_string"
            }
        }
        """
        storage = get_storage()

        if not storage:
            return jsonify({"error": "Storage not available"}), 503

        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body required"}), 400

        required = ["session_id", "camera_id", "file", "checksum"]
        missing = [f for f in required if f not in data]
        if missing:
            return jsonify({"error": f"Missing fields: {missing}"}), 400

        checksum = data.get("checksum", {})
        if not checksum.get("algo") or not checksum.get("value"):
            return jsonify({"error": "Invalid checksum format"}), 400

        result = storage.confirm_offload(
            session_id=data["session_id"],
            camera_id=data["camera_id"],
            filename=data["file"],
            checksum_algo=checksum["algo"],
            checksum_value=checksum["value"]
        )

        if result.get("success"):
            return jsonify(result), 200
        return jsonify(result), 400

    @api.route("/recordings/<recording_id>", methods=["DELETE"])
    def delete_recording(recording_id):
        """Delete a specific recording."""
        storage = get_storage()

        if not storage:
            return jsonify({"error": "Storage not available"}), 503

        result = storage.delete_recording(recording_id)
        if result.get("success"):
            return jsonify(result), 200
        return jsonify(result), 400

    @api.route("/recordings/cleanup", methods=["POST"])
    def cleanup_recordings():
        """Delete all offloaded recordings."""
        storage = get_storage()

        if not storage:
            return jsonify({"error": "Storage not available"}), 503

        result = storage.cleanup_offloaded()
        return jsonify(result)

    # =========================================================================
    # Configuration Endpoints
    # =========================================================================

    @api.route("/config", methods=["GET"])
    def get_configuration():
        """Get current configuration."""
        config = get_config()
        return jsonify(config.to_dict())

    @api.route("/config", methods=["POST"])
    def update_configuration():
        """
        Update configuration.

        Request body: Partial or full config object
        """
        config = get_config()
        recorder = get_recorder()

        # Don't allow config changes while recording
        if recorder and recorder.recording_state.is_recording:
            return jsonify({
                "error": "Cannot change config while recording"
            }), 409

        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body required"}), 400

        try:
            config.update_from_dict(data)
            config.save()
            return jsonify({
                "success": True,
                "config": config.to_dict()
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    # =========================================================================
    # Self-Test Endpoint
    # =========================================================================

    @api.route("/selftest", methods=["POST"])
    def run_selftest():
        """
        Run self-test (10-second test recording).

        Returns test results with pass/fail status.
        """
        recorder = get_recorder()

        if not recorder:
            return jsonify({"error": "Recorder not available"}), 503

        if recorder.recording_state.is_recording:
            return jsonify({
                "error": "Cannot run test while recording"
            }), 409

        result = recorder.run_test_recording()
        status_code = 200 if result.get("passed") else 500
        return jsonify(result), status_code

    # =========================================================================
    # System Control Endpoints
    # =========================================================================

    @api.route("/shutdown", methods=["POST"])
    def shutdown_node():
        """
        Shutdown the node gracefully.

        Request body (optional):
        {
            "force": false
        }
        """
        recorder = get_recorder()

        # Check if recording
        if recorder and recorder.recording_state.is_recording:
            data = request.get_json() or {}
            if not data.get("force"):
                return jsonify({
                    "error": "Recording in progress. Use force=true to override"
                }), 409

            # Stop recording first
            recorder.stop_recording()

        # Schedule shutdown
        import threading
        def do_shutdown():
            import time
            time.sleep(2)  # Give time for response to be sent
            os.system("sudo shutdown -h now")

        threading.Thread(target=do_shutdown, daemon=True).start()

        return jsonify({
            "success": True,
            "message": "Shutdown initiated"
        })

    @api.route("/reboot", methods=["POST"])
    def reboot_node():
        """Reboot the node."""
        recorder = get_recorder()

        if recorder and recorder.recording_state.is_recording:
            return jsonify({
                "error": "Recording in progress"
            }), 409

        import threading
        def do_reboot():
            import time
            time.sleep(2)
            os.system("sudo reboot")

        threading.Thread(target=do_reboot, daemon=True).start()

        return jsonify({
            "success": True,
            "message": "Reboot initiated"
        })

    # =========================================================================
    # Update Endpoints
    # =========================================================================

    @api.route("/update/check", methods=["POST"])
    def check_update():
        """Check for available updates."""
        updater = get_updater()

        if not updater:
            return jsonify({"error": "Updater not available"}), 503

        result = updater.check_for_updates()
        return jsonify(result)

    @api.route("/update/apply", methods=["POST"])
    def apply_update():
        """
        Apply available update.

        Will not proceed if recording is active.
        """
        recorder = get_recorder()
        updater = get_updater()

        if not updater:
            return jsonify({"error": "Updater not available"}), 503

        if recorder and recorder.recording_state.is_recording:
            return jsonify({
                "error": "Recording in progress"
            }), 409

        result = updater.apply_update()
        return jsonify(result)

    @api.route("/update/history", methods=["GET"])
    def get_update_history():
        """Get update history."""
        updater = get_updater()

        if not updater:
            return jsonify({"error": "Updater not available"}), 503

        return jsonify({"history": updater.get_history()})

    # =========================================================================
    # Logs Endpoint (Development Mode Only)
    # =========================================================================

    @api.route("/logs", methods=["GET"])
    def get_logs():
        """
        Get recent logs.

        Only available in development mode.
        Query params:
        - lines: number of lines (default 100)
        - level: filter by log level
        """
        config = get_config()

        if config.production_mode:
            return jsonify({
                "message": "Logs disabled in production mode"
            }), 200

        lines = request.args.get("lines", 100, type=int)
        log_file = Path("/var/log/soccer_rig/soccer_rig.log")

        if not log_file.exists():
            return jsonify({"logs": []})

        try:
            with open(log_file, "r") as f:
                all_lines = f.readlines()
                recent = all_lines[-lines:] if len(all_lines) > lines else all_lines
                return jsonify({"logs": recent})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # =========================================================================
    # Sync Endpoints
    # =========================================================================

    @api.route("/sync/status", methods=["GET"])
    def get_sync_status():
        """Get time synchronization status."""
        sync = get_sync()

        if not sync:
            return jsonify({"error": "Sync not available"}), 503

        return jsonify(sync.get_status())

    @api.route("/sync/trigger", methods=["POST"])
    def trigger_sync():
        """Trigger immediate time sync."""
        sync = get_sync()

        if not sync:
            return jsonify({"error": "Sync not available"}), 503

        result = sync.force_sync()
        return jsonify(result)

    # =========================================================================
    # Network Endpoints
    # =========================================================================

    @api.route("/network/status", methods=["GET"])
    def get_network_status():
        """Get network status."""
        network = get_network()

        if not network:
            return jsonify({"error": "Network manager not available"}), 503

        return jsonify(network.get_status())

    @api.route("/network/peers", methods=["GET"])
    def get_peers():
        """Get list of discovered peer nodes."""
        network = get_network()

        if not network:
            return jsonify({"error": "Network manager not available"}), 503

        return jsonify({"peers": network.get_peers()})

    @api.route("/network/ap/enable", methods=["POST"])
    def enable_ap_mode():
        """Enable access point mode."""
        network = get_network()

        if not network:
            return jsonify({"error": "Network manager not available"}), 503

        result = network.enable_ap_mode()
        return jsonify(result)

    @api.route("/network/ap/disable", methods=["POST"])
    def disable_ap_mode():
        """Disable access point mode."""
        network = get_network()

        if not network:
            return jsonify({"error": "Network manager not available"}), 503

        result = network.disable_ap_mode()
        return jsonify(result)

    # =========================================================================
    # Mode Switch
    # =========================================================================

    @api.route("/mode", methods=["POST"])
    def switch_mode():
        """
        Switch between production and development mode.

        Request body:
        {
            "production_mode": true/false
        }
        """
        config = get_config()
        data = request.get_json()

        if data is None or "production_mode" not in data:
            return jsonify({"error": "production_mode required"}), 400

        config.production_mode = data["production_mode"]
        config.save()

        return jsonify({
            "success": True,
            "production_mode": config.production_mode
        })

    # =========================================================================
    # Helper Functions
    # =========================================================================

    def _get_system_status():
        """Get system health metrics."""
        import psutil

        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage("/")

            # Get temperature
            temp = 0.0
            try:
                with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                    temp = int(f.read().strip()) / 1000.0
            except Exception:
                pass

            # Get battery if available
            battery = None
            try:
                battery_info = psutil.sensors_battery()
                if battery_info:
                    battery = {
                        "percent": battery_info.percent,
                        "power_plugged": battery_info.power_plugged,
                    }
            except Exception:
                pass

            return {
                "cpu_percent": cpu_percent,
                "memory_percent": memory.percent,
                "memory_available_mb": memory.available / (1024 * 1024),
                "disk_percent": disk.percent,
                "disk_free_gb": disk.free / (1024 * 1024 * 1024),
                "temperature_c": temp,
                "battery": battery,
            }
        except Exception as e:
            logger.error(f"Error getting system status: {e}")
            return {}

    return api
