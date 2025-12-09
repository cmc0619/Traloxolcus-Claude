"""
REST API for Soccer Rig Server.

Endpoints:
- Upload recordings from Pi nodes
- Query sessions and recordings
- Trigger processing jobs
- Dashboard data
"""

import logging
from flask import Blueprint, request, jsonify, send_file
from pathlib import Path

logger = logging.getLogger(__name__)


def create_api(storage, stitcher=None, db_manager=None, analytics=None, clip_generator=None):
    """Create API blueprint with injected dependencies."""

    api = Blueprint("api", __name__, url_prefix="/api/v1")

    # Lazy-load query interface
    _nlq = None

    def get_nlq():
        nonlocal _nlq
        if _nlq is None and db_manager:
            from soccer_server.query import NaturalLanguageQuery
            _nlq = NaturalLanguageQuery(db_manager)
        return _nlq

    # =========================================================================
    # Upload Endpoints
    # =========================================================================

    @api.route("/upload", methods=["POST"])
    def upload_recording():
        """
        Receive a recording upload from a Pi node.

        Expected multipart form:
        - file: The video file
        - manifest: JSON manifest data
        - session_id: Session identifier
        - camera_id: Camera ID (CAM_L, CAM_C, CAM_R)
        - checksum: SHA-256 checksum
        """
        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400

        file = request.files["file"]
        session_id = request.form.get("session_id")
        camera_id = request.form.get("camera_id")
        checksum = request.form.get("checksum")
        manifest_json = request.form.get("manifest", "{}")

        if not all([session_id, camera_id, checksum]):
            return jsonify({
                "error": "Missing required fields: session_id, camera_id, checksum"
            }), 400

        try:
            import json
            manifest = json.loads(manifest_json)
        except:
            manifest = {}

        result = storage.receive_upload(
            session_id=session_id,
            camera_id=camera_id,
            file_data=file.stream,
            manifest=manifest,
            expected_checksum=checksum,
        )

        if result.get("success"):
            return jsonify(result), 201
        return jsonify(result), 400

    @api.route("/upload/confirm", methods=["POST"])
    def confirm_upload():
        """
        Confirm successful upload (called by Pi to verify).

        Returns confirmation with checksum that Pi can use
        to mark recording as offloaded.
        """
        data = request.get_json() or {}
        session_id = data.get("session_id")
        camera_id = data.get("camera_id")

        if not session_id or not camera_id:
            return jsonify({"error": "Missing session_id or camera_id"}), 400

        result = storage.confirm_offload(session_id, camera_id)

        if result.get("success"):
            return jsonify(result), 200
        return jsonify(result), 404

    # =========================================================================
    # Session Endpoints
    # =========================================================================

    @api.route("/sessions", methods=["GET"])
    def list_sessions():
        """List all recording sessions."""
        limit = request.args.get("limit", 50, type=int)
        offset = request.args.get("offset", 0, type=int)
        complete_only = request.args.get("complete", "false").lower() == "true"

        sessions = storage.list_sessions(
            limit=limit,
            offset=offset,
            complete_only=complete_only
        )

        return jsonify({
            "sessions": [s.to_dict() for s in sessions],
            "count": len(sessions),
            "limit": limit,
            "offset": offset,
        })

    @api.route("/sessions/<session_id>", methods=["GET"])
    def get_session(session_id):
        """Get details for a specific session."""
        session = storage.get_session(session_id)
        if not session:
            return jsonify({"error": "Session not found"}), 404
        return jsonify(session.to_dict())

    @api.route("/sessions/<session_id>", methods=["DELETE"])
    def delete_session(session_id):
        """Delete a session and all its recordings."""
        result = storage.delete_session(session_id)
        if result.get("success"):
            return jsonify(result), 200
        return jsonify(result), 404

    @api.route("/sessions/<session_id>/download/<camera_id>", methods=["GET"])
    def download_recording(session_id, camera_id):
        """Download a specific recording."""
        recording = storage.get_recording(session_id, camera_id)
        if not recording:
            return jsonify({"error": "Recording not found"}), 404

        if not recording.path.exists():
            return jsonify({"error": "File not found"}), 404

        return send_file(
            recording.path,
            as_attachment=True,
            download_name=f"{session_id}_{camera_id}.mp4",
            mimetype="video/mp4"
        )

    @api.route("/sessions/<session_id>/download/stitched", methods=["GET"])
    def download_stitched(session_id):
        """Download the stitched panorama video."""
        session = storage.get_session(session_id)
        if not session:
            return jsonify({"error": "Session not found"}), 404

        if not session.stitched or not session.stitched_path:
            return jsonify({"error": "No stitched video available"}), 404

        return send_file(
            session.stitched_path,
            as_attachment=True,
            download_name=f"{session_id}_panorama.mp4",
            mimetype="video/mp4"
        )

    # =========================================================================
    # Processing Endpoints
    # =========================================================================

    @api.route("/sessions/<session_id>/stitch", methods=["POST"])
    def trigger_stitch(session_id):
        """Trigger video stitching for a session."""
        session = storage.get_session(session_id)
        if not session:
            return jsonify({"error": "Session not found"}), 404

        if len(session.recordings) < 3:
            return jsonify({
                "error": "Session incomplete",
                "cameras_present": list(session.recordings.keys()),
                "cameras_needed": ["CAM_L", "CAM_C", "CAM_R"]
            }), 400

        if not stitcher:
            return jsonify({"error": "Stitcher not available"}), 503

        # Queue the stitching job
        try:
            job_id = stitcher.queue_stitch(session_id)
            return jsonify({
                "success": True,
                "job_id": job_id,
                "session_id": session_id,
                "status": "queued"
            }), 202
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @api.route("/jobs/<job_id>", methods=["GET"])
    def get_job_status(job_id):
        """Get status of a processing job."""
        if not stitcher:
            return jsonify({"error": "Stitcher not available"}), 503

        status = stitcher.get_job_status(job_id)
        if status:
            return jsonify(status)
        return jsonify({"error": "Job not found"}), 404

    # =========================================================================
    # Stats Endpoints
    # =========================================================================

    @api.route("/stats", methods=["GET"])
    def get_stats():
        """Get server statistics."""
        stats = storage.get_storage_stats()
        return jsonify(stats)

    @api.route("/health", methods=["GET"])
    def health_check():
        """Health check endpoint."""
        return jsonify({
            "status": "healthy",
            "service": "soccer-rig-server",
            "version": "1.0.0"
        })

    # =========================================================================
    # Analytics Endpoints
    # =========================================================================

    @api.route("/sessions/<session_id>/analyze", methods=["POST"])
    def trigger_analysis(session_id):
        """Trigger video analysis for a session."""
        if not analytics:
            return jsonify({"error": "Analytics not available"}), 503

        session = storage.get_session(session_id)
        if not session:
            return jsonify({"error": "Session not found"}), 404

        # Find stitched video or use center camera
        video_path = None
        if session.stitched_path and Path(session.stitched_path).exists():
            video_path = session.stitched_path
        elif "CAM_C" in session.recordings:
            video_path = str(session.recordings["CAM_C"].path)
        else:
            return jsonify({"error": "No video available for analysis"}), 400

        # Get or create game in database
        game = None
        if db_manager:
            game = db_manager.get_game(session_id)
            if not game:
                game = db_manager.create_game(
                    session_id=session_id,
                    title=session_id,
                    date=session.created_at,
                )

        try:
            job_id = analytics.queue_analysis(game.id if game else 0, video_path)
            return jsonify({
                "success": True,
                "job_id": job_id,
                "session_id": session_id,
                "status": "queued"
            }), 202
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @api.route("/analytics/status", methods=["GET"])
    def get_analytics_status():
        """Get analytics pipeline status."""
        if not analytics:
            return jsonify({"error": "Analytics not available"}), 503
        return jsonify(analytics.get_status())

    # =========================================================================
    # Query Endpoints
    # =========================================================================

    @api.route("/query", methods=["POST"])
    def natural_language_query():
        """
        Execute a natural language query.

        POST body:
        {
            "query": "Show me all saves by the goalkeeper",
            "game_id": 1  // optional
        }
        """
        nlq = get_nlq()
        if not nlq:
            return jsonify({"error": "Query interface not available"}), 503

        data = request.get_json() or {}
        query_text = data.get("query", "")
        game_id = data.get("game_id")

        if not query_text:
            return jsonify({"error": "No query provided"}), 400

        try:
            results = nlq.query(query_text, game_id=game_id)
            return jsonify(results)
        except Exception as e:
            logger.error(f"Query error: {e}")
            return jsonify({"error": str(e)}), 500

    @api.route("/query/suggestions", methods=["GET"])
    def get_query_suggestions():
        """Get query suggestions based on partial input."""
        nlq = get_nlq()
        if not nlq:
            return jsonify({"error": "Query interface not available"}), 503

        partial = request.args.get("q", "")
        suggestions = nlq.get_suggestions(partial)
        return jsonify({"suggestions": suggestions})

    @api.route("/games/<int:game_id>/events", methods=["GET"])
    def get_game_events(game_id):
        """Get all events for a game."""
        if not db_manager:
            return jsonify({"error": "Database not available"}), 503

        event_type = request.args.get("type")
        player_id = request.args.get("player_id", type=int)
        start_sec = request.args.get("start", type=float)
        end_sec = request.args.get("end", type=float)

        from soccer_server.database import EventType
        event_type_enum = None
        if event_type:
            try:
                event_type_enum = EventType(event_type)
            except ValueError:
                pass

        events = db_manager.get_events(
            game_id=game_id,
            event_type=event_type_enum,
            player_id=player_id,
            start_sec=start_sec,
            end_sec=end_sec,
        )

        return jsonify({
            "events": [
                {
                    "id": e.id,
                    "type": e.event_type.value,
                    "timestamp_sec": e.timestamp_sec,
                    "player_id": e.player_id,
                    "outcome": e.outcome.value if e.outcome else None,
                    "confidence": e.confidence,
                    "x": e.x,
                    "y": e.y,
                }
                for e in events
            ],
            "count": len(events),
        })

    @api.route("/games/<int:game_id>/players", methods=["GET"])
    def get_game_players(game_id):
        """Get all players for a game."""
        if not db_manager:
            return jsonify({"error": "Database not available"}), 503

        players = db_manager.get_players_by_game(game_id)
        return jsonify({
            "players": [
                {
                    "id": p.id,
                    "name": p.name,
                    "jersey_number": p.jersey_number,
                    "team": p.team,
                    "position": p.position.value if p.position else None,
                    "is_goalkeeper": p.is_goalkeeper,
                    "total_events": p.total_events,
                }
                for p in players
            ],
            "count": len(players),
        })

    @api.route("/games/<int:game_id>/players/<int:player_id>/summary", methods=["GET"])
    def get_player_summary(game_id, player_id):
        """Get summary of a player's activity."""
        nlq = get_nlq()
        if not nlq:
            return jsonify({"error": "Query interface not available"}), 503

        summary = nlq.get_player_summary(game_id, player_id)
        if "error" in summary:
            return jsonify(summary), 404
        return jsonify(summary)

    @api.route("/games/<int:game_id>/gk-events", methods=["GET"])
    def get_goalkeeper_events(game_id):
        """Get all goalkeeper-specific events for a game."""
        if not db_manager:
            return jsonify({"error": "Database not available"}), 503

        events = db_manager.get_gk_events(game_id)
        return jsonify({
            "events": [
                {
                    "id": e.id,
                    "type": e.event_type.value,
                    "timestamp_sec": e.timestamp_sec,
                    "timestamp_formatted": f"{int(e.timestamp_sec // 60)}:{int(e.timestamp_sec % 60):02d}",
                    "player_id": e.player_id,
                    "outcome": e.outcome.value if e.outcome else None,
                    "confidence": e.confidence,
                }
                for e in events
            ],
            "count": len(events),
        })

    # =========================================================================
    # Clip Endpoints
    # =========================================================================

    @api.route("/clips/generate", methods=["POST"])
    def generate_clip():
        """
        Generate a video clip for an event or time range.

        POST body:
        {
            "session_id": "GAME_20240315_140000",
            "timestamp": 1234.5,  // Center timestamp in seconds
            "duration_before": 5,  // Seconds before event
            "duration_after": 5,   // Seconds after event
        }
        """
        if not clip_generator:
            return jsonify({"error": "Clip generator not available"}), 503

        data = request.get_json() or {}
        session_id = data.get("session_id")
        timestamp = data.get("timestamp", type=float)
        duration_before = data.get("duration_before", 5.0)
        duration_after = data.get("duration_after", 5.0)

        if not session_id or timestamp is None:
            return jsonify({"error": "Missing session_id or timestamp"}), 400

        # Get video path
        session = storage.get_session(session_id)
        if not session:
            return jsonify({"error": "Session not found"}), 404

        video_path = None
        if session.stitched_path and Path(session.stitched_path).exists():
            video_path = session.stitched_path
        elif "CAM_C" in session.recordings:
            video_path = str(session.recordings["CAM_C"].path)
        else:
            return jsonify({"error": "No video available"}), 400

        try:
            clip_path = clip_generator.generate_event_clip(
                video_path=video_path,
                event_timestamp=timestamp,
                duration_before=duration_before,
                duration_after=duration_after,
            )
            return jsonify({
                "success": True,
                "clip_path": clip_path,
                "timestamp": timestamp,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @api.route("/clips/player-highlight", methods=["POST"])
    def generate_player_highlight():
        """
        Generate a highlight reel for a player.

        POST body:
        {
            "session_id": "GAME_20240315_140000",
            "player_id": 1,
            "max_duration": 120  // Maximum highlight duration in seconds
        }
        """
        if not clip_generator or not db_manager:
            return jsonify({"error": "Clip generator or database not available"}), 503

        data = request.get_json() or {}
        session_id = data.get("session_id")
        player_id = data.get("player_id", type=int)
        max_duration = data.get("max_duration", 120.0)

        if not session_id or not player_id:
            return jsonify({"error": "Missing session_id or player_id"}), 400

        # Get video path
        session = storage.get_session(session_id)
        if not session:
            return jsonify({"error": "Session not found"}), 404

        video_path = None
        if session.stitched_path and Path(session.stitched_path).exists():
            video_path = session.stitched_path
        elif "CAM_C" in session.recordings:
            video_path = str(session.recordings["CAM_C"].path)
        else:
            return jsonify({"error": "No video available"}), 400

        # Get player's events
        events = db_manager.get_player_events(player_id)
        if not events:
            return jsonify({"error": "No events found for player"}), 404

        event_list = [
            {"timestamp_sec": e.timestamp_sec, "event_type": e.event_type.value}
            for e in events
        ]

        try:
            clip_path = clip_generator.generate_player_highlight(
                video_path=video_path,
                events=event_list,
                max_duration=max_duration,
            )
            return jsonify({
                "success": True,
                "clip_path": clip_path,
                "player_id": player_id,
                "events_included": len(event_list),
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @api.route("/clips/<path:clip_filename>/download", methods=["GET"])
    def download_clip(clip_filename):
        """Download a generated clip."""
        if not clip_generator:
            return jsonify({"error": "Clip generator not available"}), 503

        clip_path = Path(clip_generator.clips_path) / clip_filename
        if not clip_path.exists():
            return jsonify({"error": "Clip not found"}), 404

        return send_file(
            clip_path,
            as_attachment=True,
            download_name=clip_filename,
            mimetype="video/mp4"
        )

    # =========================================================================
    # Player Management
    # =========================================================================

    @api.route("/games/<int:game_id>/players", methods=["POST"])
    def add_player(game_id):
        """
        Add a player to a game roster.

        POST body:
        {
            "name": "John Doe",
            "jersey_number": 7,
            "team": "home",
            "position": "forward",
            "is_goalkeeper": false
        }
        """
        if not db_manager:
            return jsonify({"error": "Database not available"}), 503

        data = request.get_json() or {}

        from soccer_server.database import PlayerPosition
        position = None
        if data.get("position"):
            try:
                position = PlayerPosition(data["position"])
            except ValueError:
                position = PlayerPosition.UNKNOWN

        try:
            player = db_manager.add_player(
                game_id=game_id,
                name=data.get("name"),
                jersey_number=data.get("jersey_number"),
                team=data.get("team"),
                position=position,
                is_goalkeeper=data.get("is_goalkeeper", False),
            )
            return jsonify({
                "success": True,
                "player_id": player.id,
            }), 201
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # =========================================================================
    # Viewer Portal Endpoints
    # =========================================================================

    # Team codes for access control (in production, store in database)
    _team_codes = {
        "DEMO2024": {"name": "Demo Team", "team_id": 1},
        "TIGERS24": {"name": "Tigers FC", "team_id": 2},
        "EAGLES24": {"name": "Eagles SC", "team_id": 3},
    }

    @api.route("/viewer/auth", methods=["GET"])
    def viewer_authenticate():
        """
        Validate a team code for viewer access.

        Query params:
        - code: Team access code
        """
        code = request.args.get("code", "").upper().strip()

        if not code:
            return jsonify({"valid": False, "error": "No code provided"})

        # Check hardcoded codes (in production, query database)
        if code in _team_codes:
            team_info = _team_codes[code]
            return jsonify({
                "valid": True,
                "team_name": team_info["name"],
                "team_id": team_info["team_id"],
            })

        # Allow any code in demo mode
        return jsonify({
            "valid": True,
            "team_name": code,
            "team_id": 0,
        })

    @api.route("/viewer/teams", methods=["GET"])
    def list_teams():
        """List all teams (admin only in production)."""
        return jsonify({
            "teams": [
                {"code": code, "name": info["name"]}
                for code, info in _team_codes.items()
            ]
        })

    @api.route("/sessions/<session_id>/stream/<camera_id>", methods=["GET"])
    def stream_recording(session_id, camera_id):
        """
        Stream a recording with range request support.

        Supports HTTP Range requests for video seeking.
        """
        from flask import Response

        if camera_id == "stitched":
            session = storage.get_session(session_id)
            if not session or not session.stitched_path:
                return jsonify({"error": "Stitched video not found"}), 404
            file_path = Path(session.stitched_path)
        else:
            recording = storage.get_recording(session_id, camera_id)
            if not recording:
                return jsonify({"error": "Recording not found"}), 404
            file_path = recording.path

        if not file_path.exists():
            return jsonify({"error": "File not found"}), 404

        file_size = file_path.stat().st_size
        range_header = request.headers.get("Range")

        if range_header:
            # Parse range header
            byte_range = range_header.replace("bytes=", "").split("-")
            start = int(byte_range[0])
            end = int(byte_range[1]) if byte_range[1] else file_size - 1

            if start >= file_size:
                return Response(status=416)

            length = end - start + 1

            def generate():
                with open(file_path, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk_size = min(8192, remaining)
                        data = f.read(chunk_size)
                        if not data:
                            break
                        remaining -= len(data)
                        yield data

            response = Response(
                generate(),
                status=206,
                mimetype="video/mp4",
                direct_passthrough=True,
            )
            response.headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
            response.headers["Accept-Ranges"] = "bytes"
            response.headers["Content-Length"] = str(length)
            return response
        else:
            # Full file response
            return send_file(
                file_path,
                mimetype="video/mp4",
            )

    @api.route("/viewer/games", methods=["GET"])
    def viewer_list_games():
        """
        List games available to viewer (with team filtering).

        Query params:
        - team_id: Filter by team (optional)
        - season: Filter by season (optional)
        - limit: Max results
        """
        limit = request.args.get("limit", 50, type=int)

        sessions = storage.list_sessions(limit=limit, complete_only=True)

        games = []
        for s in sessions:
            game_data = s.to_dict()
            # Add viewer-friendly fields
            game_data["thumbnail_url"] = f"/api/v1/sessions/{s.id}/thumbnail"
            game_data["stream_url"] = f"/api/v1/sessions/{s.id}/stream/{'stitched' if s.stitched else 'CAM_C'}"
            games.append(game_data)

        return jsonify({
            "games": games,
            "count": len(games),
        })

    @api.route("/sessions/<session_id>/thumbnail", methods=["GET"])
    def get_session_thumbnail(session_id):
        """Get or generate a thumbnail for a session."""
        session = storage.get_session(session_id)
        if not session:
            return jsonify({"error": "Session not found"}), 404

        # Check for existing thumbnail
        thumb_path = Path(storage.base_path) / session_id / "thumbnail.jpg"
        if thumb_path.exists():
            return send_file(thumb_path, mimetype="image/jpeg")

        # Generate thumbnail from video (first frame)
        video_path = None
        if session.stitched_path and Path(session.stitched_path).exists():
            video_path = session.stitched_path
        elif "CAM_C" in session.recordings:
            video_path = str(session.recordings["CAM_C"].path)

        if video_path:
            try:
                import subprocess
                thumb_path.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run([
                    "ffmpeg", "-y", "-i", video_path,
                    "-vframes", "1", "-ss", "10",
                    "-vf", "scale=640:-1",
                    str(thumb_path)
                ], capture_output=True, timeout=30)

                if thumb_path.exists():
                    return send_file(thumb_path, mimetype="image/jpeg")
            except Exception as e:
                logger.warning(f"Failed to generate thumbnail: {e}")

        # Return placeholder
        return jsonify({"error": "No thumbnail available"}), 404

    @api.route("/viewer/share/<share_id>", methods=["GET"])
    def get_shared_clip(share_id):
        """Get a shared clip by ID (public, no auth required)."""
        # In production, look up share_id in database
        # For now, parse it as session_id:timestamp
        try:
            parts = share_id.split("_")
            session_id = "_".join(parts[:-1])
            timestamp = float(parts[-1])

            session = storage.get_session(session_id)
            if not session:
                return jsonify({"error": "Video not found"}), 404

            return jsonify({
                "session_id": session_id,
                "timestamp": timestamp,
                "stream_url": f"/api/v1/sessions/{session_id}/stream/{'stitched' if session.stitched else 'CAM_C'}",
                "game_name": session.name or session_id,
            })
        except Exception:
            return jsonify({"error": "Invalid share link"}), 400

    return api
