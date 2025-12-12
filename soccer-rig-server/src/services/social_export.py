"""
Social Media Export Service

Generates vertical 9:16 clips optimized for social media:
- TikTok, Instagram Reels, YouTube Shorts
- Auto-crop from panorama to follow action
- Add overlays (player name, event type, score)
- Watermark/branding support
"""

import os
import subprocess
import tempfile
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from datetime import datetime
import logging
import json

logger = logging.getLogger(__name__)

# Aspect ratios
ASPECT_9_16 = (9, 16)  # Vertical (TikTok, Reels, Shorts)
ASPECT_1_1 = (1, 1)    # Square (Instagram feed)
ASPECT_16_9 = (16, 9)  # Horizontal (YouTube, Twitter)


@dataclass
class SocialClipConfig:
    """Configuration for social media clip generation."""
    aspect_ratio: Tuple[int, int] = ASPECT_9_16
    max_duration: int = 60  # seconds
    output_resolution: Tuple[int, int] = (1080, 1920)  # width, height for 9:16
    fps: int = 30

    # Overlay options
    show_player_name: bool = True
    show_event_type: bool = True
    show_score: bool = False
    show_timestamp: bool = True

    # Branding
    watermark_path: Optional[str] = None
    watermark_position: str = "bottom_right"  # top_left, top_right, bottom_left, bottom_right
    watermark_opacity: float = 0.7

    # Colors
    overlay_bg_color: str = "rgba(0,0,0,0.6)"
    text_color: str = "white"
    accent_color: str = "#10b981"


class SocialMediaExporter:
    """
    Export clips formatted for social media platforms.

    Takes source video + event data and produces vertical clips
    with automatic cropping to follow the action.
    """

    def __init__(self, config: Optional[SocialClipConfig] = None):
        self.config = config or SocialClipConfig()

    def export_clip(
        self,
        source_video: str,
        output_path: str,
        start_time: float,
        duration: float,
        focus_x: float = 0.5,  # 0-1 position in source to center on
        player_name: Optional[str] = None,
        event_type: Optional[str] = None,
        score: Optional[str] = None,
        game_info: Optional[str] = None
    ) -> Dict:
        """
        Export a single clip formatted for social media.

        Args:
            source_video: Path to source panorama video
            output_path: Where to save the output
            start_time: Start time in seconds
            duration: Duration in seconds
            focus_x: Horizontal position (0-1) to center the crop on
            player_name: Player name for overlay
            event_type: Event type (goal, save, etc.) for overlay
            score: Score string for overlay
            game_info: Game info string (opponent, date)

        Returns:
            Dict with export status and metadata
        """
        try:
            # Get source video info
            probe = self._probe_video(source_video)
            src_width = probe['width']
            src_height = probe['height']

            # Calculate crop dimensions for 9:16 from source
            target_w, target_h = self.config.output_resolution
            target_ratio = target_w / target_h

            # Calculate crop region from source
            # For 9:16 output from a wide panorama, we take a vertical slice
            crop_height = src_height
            crop_width = int(crop_height * target_ratio)

            # Ensure crop doesn't exceed source
            if crop_width > src_width:
                crop_width = src_width
                crop_height = int(crop_width / target_ratio)

            # Calculate X position for crop (centered on focus_x)
            max_x = src_width - crop_width
            crop_x = int(focus_x * max_x)
            crop_x = max(0, min(crop_x, max_x))
            crop_y = (src_height - crop_height) // 2

            # Clamp duration
            duration = min(duration, self.config.max_duration)

            # Build FFmpeg filter chain
            filters = self._build_filter_chain(
                crop_x, crop_y, crop_width, crop_height,
                player_name, event_type, score, game_info
            )

            # Run FFmpeg
            cmd = [
                'ffmpeg', '-y',
                '-ss', str(start_time),
                '-i', source_video,
                '-t', str(duration),
                '-vf', filters,
                '-c:v', 'libx264',
                '-preset', 'medium',
                '-crf', '23',
                '-c:a', 'aac',
                '-b:a', '128k',
                '-r', str(self.config.fps),
                '-movflags', '+faststart',
                output_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                logger.error(f"FFmpeg error: {result.stderr}")
                return {
                    'success': False,
                    'error': result.stderr
                }

            # Get output file info
            output_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0

            return {
                'success': True,
                'output_path': output_path,
                'duration': duration,
                'resolution': f"{target_w}x{target_h}",
                'aspect_ratio': '9:16',
                'file_size': output_size,
                'file_size_mb': round(output_size / (1024 * 1024), 2)
            }

        except Exception as e:
            logger.error(f"Export failed: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def _probe_video(self, video_path: str) -> Dict:
        """Get video metadata using ffprobe."""
        cmd = [
            'ffprobe', '-v', 'quiet',
            '-print_format', 'json',
            '-show_streams',
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(result.stdout)

        video_stream = next(
            (s for s in data['streams'] if s['codec_type'] == 'video'),
            None
        )

        if not video_stream:
            raise ValueError("No video stream found")

        return {
            'width': int(video_stream['width']),
            'height': int(video_stream['height']),
            'duration': float(video_stream.get('duration', 0)),
            'fps': self._parse_frame_rate(video_stream.get('r_frame_rate', '30/1'))
        }

    def _parse_frame_rate(self, rate_str: str) -> float:
        """Safely parse frame rate string like '30/1' or '30'."""
        try:
            if '/' in rate_str:
                num, denom = rate_str.split('/', 1)
                return float(num) / float(denom)
            return float(rate_str)
        except (ValueError, ZeroDivisionError):
            return 30.0  # Default fallback

    def _sanitize_text(self, text: str) -> str:
        """
        Escape text for FFmpeg drawtext filter to prevent command injection.
        
        FFmpeg drawtext uses special syntax where certain characters have special
        meaning. We must escape them to prevent injection attacks.
        """
        if not text:
            return ''
        
        # Limit text length to prevent buffer issues
        text = text[:100]
        
        # Remove any control characters and newlines
        text = ''.join(c for c in text if c.isprintable() and c not in '\n\r\t')
        
        # Escape characters that have special meaning in FFmpeg drawtext filter
        # Order matters: escape backslash first
        text = text.replace('\\', '\\\\')
        text = text.replace("'", r"\'")
        text = text.replace(':', '\\:')
        text = text.replace(';', '\\;')  # Command separator
        text = text.replace('%', '%%')   # FFmpeg format specifier
        text = text.replace('[', '\\[')
        text = text.replace(']', '\\]')
        
        return text

    def _build_filter_chain(
        self,
        crop_x: int, crop_y: int,
        crop_w: int, crop_h: int,
        player_name: Optional[str],
        event_type: Optional[str],
        score: Optional[str],
        game_info: Optional[str]
    ) -> str:
        """Build FFmpeg filter chain for crop and overlays."""
        target_w, target_h = self.config.output_resolution
        filters = []

        # Crop from source
        filters.append(f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}")

        # Scale to target resolution
        filters.append(f"scale={target_w}:{target_h}")

        # Add text overlays (sanitize all text to prevent FFmpeg command injection)
        if self.config.show_event_type and event_type:
            event_display = self._sanitize_text(self._format_event_type(event_type))
            # Event type at top
            filters.append(
                f"drawtext=text='{event_display}':"
                f"fontsize=72:fontcolor=white:"
                f"borderw=3:bordercolor=black:"
                f"x=(w-text_w)/2:y=100"
            )

        if self.config.show_player_name and player_name:
            # Player name below event
            safe_name = self._sanitize_text(player_name)
            filters.append(
                f"drawtext=text='{safe_name}':"
                f"fontsize=48:fontcolor=white:"
                f"borderw=2:bordercolor=black:"
                f"x=(w-text_w)/2:y=180"
            )

        if self.config.show_score and score:
            # Score at bottom
            safe_score = self._sanitize_text(score)
            filters.append(
                f"drawtext=text='{safe_score}':"
                f"fontsize=36:fontcolor=white:"
                f"borderw=2:bordercolor=black:"
                f"x=(w-text_w)/2:y=h-150"
            )

        if game_info:
            # Game info at very bottom
            safe_info = self._sanitize_text(game_info)
            filters.append(
                f"drawtext=text='{safe_info}':"
                f"fontsize=28:fontcolor=white:"
                f"borderw=2:bordercolor=black:"
                f"x=(w-text_w)/2:y=h-100"
            )

        # Add watermark if configured
        # (would need overlay filter with watermark image)

        return ','.join(filters)

    def _format_event_type(self, event_type: str) -> str:
        """Format event type for display."""
        formats = {
            'goal': 'GOAL!',
            'shot': 'SHOT',
            'shot_on_target': 'SHOT ON TARGET',
            'save': 'GREAT SAVE!',
            'save_diving': 'DIVING SAVE!',
            'assist': 'ASSIST',
            'tackle': 'TACKLE',
            'dribble': 'SKILL MOVE'
        }
        return formats.get(event_type, event_type.upper())

    def export_highlight_reel(
        self,
        clips: List[Dict],
        output_path: str,
        title: Optional[str] = None,
        add_transitions: bool = True
    ) -> Dict:
        """
        Combine multiple clips into a highlight reel.

        Args:
            clips: List of clip dicts with source_video, start_time, duration, etc.
            output_path: Where to save the combined output
            title: Optional title card at start
            add_transitions: Add fade transitions between clips

        Returns:
            Export status dict
        """
        if not clips:
            return {'success': False, 'error': 'No clips provided'}

        try:
            # Export individual clips to temp files
            temp_files = []
            with tempfile.TemporaryDirectory() as temp_dir:
                for i, clip in enumerate(clips):
                    temp_path = os.path.join(temp_dir, f"clip_{i:03d}.mp4")
                    result = self.export_clip(
                        source_video=clip['source_video'],
                        output_path=temp_path,
                        start_time=clip['start_time'],
                        duration=clip.get('duration', 10),
                        focus_x=clip.get('focus_x', 0.5),
                        player_name=clip.get('player_name'),
                        event_type=clip.get('event_type')
                    )
                    if result['success']:
                        temp_files.append(temp_path)

                if not temp_files:
                    return {'success': False, 'error': 'No clips exported successfully'}

                # Create concat file
                concat_file = os.path.join(temp_dir, 'concat.txt')
                with open(concat_file, 'w') as f:
                    for temp_file in temp_files:
                        f.write(f"file '{temp_file}'\n")

                # Concat clips
                cmd = [
                    'ffmpeg', '-y',
                    '-f', 'concat',
                    '-safe', '0',
                    '-i', concat_file,
                    '-c', 'copy',
                    output_path
                ]

                result = subprocess.run(cmd, capture_output=True, text=True)

                if result.returncode != 0:
                    return {'success': False, 'error': result.stderr}

            output_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0

            return {
                'success': True,
                'output_path': output_path,
                'clip_count': len(temp_files),
                'file_size_mb': round(output_size / (1024 * 1024), 2)
            }

        except Exception as e:
            logger.error(f"Highlight reel export failed: {e}")
            return {'success': False, 'error': str(e)}


# =============================================================================
# Flask Routes
# =============================================================================

def register_social_routes(app, db):
    """Register social media export routes."""
    from flask import jsonify, request, send_file, render_template_string, session
    from ..auth import login_required

    exporter = SocialMediaExporter()

    @app.route('/api/social/export', methods=['POST'])
    @login_required
    def api_social_export():
        """Export a clip for social media."""
        from ..models import Clip, Game, GameEvent, Player

        data = request.get_json()
        clip_id = data.get('clip_id')
        event_id = data.get('event_id')

        if not clip_id and not event_id:
            return jsonify({'error': 'clip_id or event_id required'}), 400

        # Get clip/event data
        if clip_id:
            clip = db.query(Clip).get(clip_id)
            if not clip:
                return jsonify({'error': 'Clip not found'}), 404

            game = clip.game
            event = clip.event
            source_video = game.panorama_url
            start_time = clip.start_time
            duration = clip.duration_seconds or 15
        else:
            event = db.query(GameEvent).get(event_id)
            if not event:
                return jsonify({'error': 'Event not found'}), 404

            game = event.game
            source_video = game.panorama_url
            start_time = max(0, event.timestamp_seconds - 5)
            duration = 15

        if not source_video or not os.path.exists(source_video):
            return jsonify({'error': 'Source video not found'}), 404

        # Get player info
        player = event.player if event else None
        player_name = player.full_name if player else None
        event_type = event.event_type.value if event and event.event_type else None

        # Focus position from event field position (use None check, 0.0 is valid)
        focus_x = event.field_position_x if event and event.field_position_x is not None else 0.5

        # Game info
        game_info = f"vs {game.opponent}" if game.opponent else None
        score = f"{game.home_score}-{game.away_score}" if game.home_score is not None else None

        # Generate output path
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_filename = f"social_{clip_id or event_id}_{timestamp}.mp4"
        output_dir = os.path.join(app.config.get('UPLOAD_FOLDER', '/tmp'), 'social')
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_filename)

        # Export
        result = exporter.export_clip(
            source_video=source_video,
            output_path=output_path,
            start_time=start_time,
            duration=min(duration, data.get('max_duration', 60)),
            focus_x=focus_x,
            player_name=player_name,
            event_type=event_type,
            score=score if data.get('show_score') else None,
            game_info=game_info
        )

        if result['success']:
            result['download_url'] = f"/api/social/download/{output_filename}"

        return jsonify(result)

    @app.route('/api/social/download/<filename>')
    @login_required
    def api_social_download(filename: str):
        """Download exported social clip."""
        # Prevent path traversal
        if '/' in filename or '\\' in filename or filename.startswith('.'):
            return jsonify({'error': 'Invalid filename'}), 400

        output_dir = os.path.join(app.config.get('UPLOAD_FOLDER', '/tmp'), 'social')
        file_path = os.path.join(output_dir, filename)

        # Verify the resolved path is within the output directory
        if not os.path.abspath(file_path).startswith(os.path.abspath(output_dir)):
            return jsonify({'error': 'Invalid filename'}), 400

        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404

        return send_file(file_path, as_attachment=True)

    @app.route('/api/social/highlight-reel', methods=['POST'])
    @login_required
    def api_social_highlight_reel():
        """Generate a highlight reel from multiple clips."""
        from ..models import Clip, GameEvent

        data = request.get_json()
        clip_ids = data.get('clip_ids', [])
        event_ids = data.get('event_ids', [])

        if not clip_ids and not event_ids:
            return jsonify({'error': 'clip_ids or event_ids required'}), 400

        clips_data = []

        # Process clips
        for clip_id in clip_ids:
            clip = db.query(Clip).get(clip_id)
            if clip and clip.game and clip.game.panorama_url:
                clips_data.append({
                    'source_video': clip.game.panorama_url,
                    'start_time': clip.start_time,
                    'duration': clip.duration_seconds or 10,
                    'focus_x': clip.event.field_position_x if clip.event and clip.event.field_position_x is not None else 0.5,
                    'player_name': clip.event.player.full_name if clip.event and clip.event.player else None,
                    'event_type': clip.event.event_type.value if clip.event and clip.event.event_type else None
                })

        # Process events
        for event_id in event_ids:
            event = db.query(GameEvent).get(event_id)
            if event and event.game and event.game.panorama_url:
                clips_data.append({
                    'source_video': event.game.panorama_url,
                    'start_time': max(0, event.timestamp_seconds - 5),
                    'duration': 10,
                    'focus_x': event.field_position_x if event.field_position_x is not None else 0.5,
                    'player_name': event.player.full_name if event.player else None,
                    'event_type': event.event_type.value if event.event_type else None
                })

        if not clips_data:
            return jsonify({'error': 'No valid clips found'}), 400

        # Generate output
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_filename = f"highlight_reel_{timestamp}.mp4"
        output_dir = os.path.join(app.config.get('UPLOAD_FOLDER', '/tmp'), 'social')
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_filename)

        result = exporter.export_highlight_reel(
            clips=clips_data,
            output_path=output_path,
            title=data.get('title')
        )

        if result['success']:
            result['download_url'] = f"/api/social/download/{output_filename}"

        return jsonify(result)

    @app.route('/social-export')
    def social_export_page():
        """Social media export UI."""
        return render_template_string(SOCIAL_EXPORT_HTML)


# =============================================================================
# Social Export HTML Template
# =============================================================================

SOCIAL_EXPORT_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Social Media Export - Soccer Rig</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0f172a; color: #f1f5f9; min-height: 100vh; }
        .header { background: linear-gradient(135deg, #7c3aed 0%, #4f46e5 100%); padding: 1.5rem 2rem; }
        .header-content { max-width: 1200px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; }
        .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
        .grid { display: grid; grid-template-columns: 1fr 300px; gap: 2rem; }
        @media (max-width: 768px) { .grid { grid-template-columns: 1fr; } }
        .card { background: #1e293b; border-radius: 1rem; padding: 1.5rem; margin-bottom: 1.5rem; }
        .card h2 { font-size: 1.25rem; margin-bottom: 1rem; color: #a5b4fc; }
        .preview-container { aspect-ratio: 9/16; max-height: 500px; background: #0f172a; border-radius: 0.5rem; display: flex; align-items: center; justify-content: center; margin-bottom: 1rem; overflow: hidden; }
        .preview-placeholder { color: #64748b; text-align: center; }
        .preview-placeholder .icon { font-size: 4rem; margin-bottom: 1rem; }
        video { max-width: 100%; max-height: 100%; }
        .platform-buttons { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1rem; }
        .platform-btn { padding: 0.5rem 1rem; border-radius: 2rem; border: 2px solid #334155; background: transparent; color: #f1f5f9; cursor: pointer; font-size: 0.875rem; }
        .platform-btn.active { background: #4f46e5; border-color: #4f46e5; }
        .form-group { margin-bottom: 1rem; }
        .form-group label { display: block; margin-bottom: 0.5rem; color: #94a3b8; font-size: 0.875rem; }
        .form-group input, .form-group select { width: 100%; padding: 0.75rem; border: 2px solid #334155; border-radius: 0.5rem; background: #0f172a; color: #f1f5f9; }
        .form-group input:focus, .form-group select:focus { outline: none; border-color: #4f46e5; }
        .checkbox-group { display: flex; align-items: center; gap: 0.5rem; }
        .checkbox-group input { width: auto; }
        .btn { padding: 0.75rem 1.5rem; border-radius: 0.5rem; border: none; cursor: pointer; font-weight: 600; }
        .btn-primary { background: linear-gradient(135deg, #7c3aed, #4f46e5); color: white; width: 100%; }
        .btn-primary:hover { opacity: 0.9; }
        .btn-secondary { background: #334155; color: #f1f5f9; }
        .clip-list { max-height: 300px; overflow-y: auto; }
        .clip-item { display: flex; align-items: center; gap: 0.75rem; padding: 0.75rem; background: #0f172a; border-radius: 0.5rem; margin-bottom: 0.5rem; cursor: pointer; }
        .clip-item:hover { background: #1e293b; }
        .clip-item.selected { border: 2px solid #4f46e5; }
        .clip-thumb { width: 60px; height: 40px; background: #334155; border-radius: 0.25rem; }
        .clip-info { flex: 1; }
        .clip-title { font-size: 0.875rem; font-weight: 500; }
        .clip-meta { font-size: 0.75rem; color: #64748b; }
        .status { padding: 1rem; border-radius: 0.5rem; margin-top: 1rem; }
        .status.success { background: #064e3b; color: #6ee7b7; }
        .status.error { background: #7f1d1d; color: #fca5a5; }
        .status.processing { background: #1e3a5f; color: #93c5fd; }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-content">
            <h1>Social Media Export</h1>
            <a href="/dashboard" style="color: white; text-decoration: none;">Back to Dashboard</a>
        </div>
    </div>
    <div class="container">
        <div class="grid">
            <div class="main-content">
                <div class="card">
                    <h2>Select Platform</h2>
                    <div class="platform-buttons">
                        <button class="platform-btn active" data-ratio="9:16" onclick="selectPlatform(this)">TikTok</button>
                        <button class="platform-btn" data-ratio="9:16" onclick="selectPlatform(this)">Instagram Reels</button>
                        <button class="platform-btn" data-ratio="9:16" onclick="selectPlatform(this)">YouTube Shorts</button>
                        <button class="platform-btn" data-ratio="1:1" onclick="selectPlatform(this)">Instagram Square</button>
                    </div>
                </div>

                <div class="card">
                    <h2>Select Clips</h2>
                    <div class="clip-list" id="clip-list">
                        <p style="color: #64748b; text-align: center; padding: 2rem;">Loading clips...</p>
                    </div>
                </div>

                <div class="card">
                    <h2>Export Options</h2>
                    <div class="form-group">
                        <label>Max Duration (seconds)</label>
                        <input type="number" id="max-duration" value="60" min="5" max="180">
                    </div>
                    <div class="form-group checkbox-group">
                        <input type="checkbox" id="show-player-name" checked>
                        <label for="show-player-name">Show player name</label>
                    </div>
                    <div class="form-group checkbox-group">
                        <input type="checkbox" id="show-event-type" checked>
                        <label for="show-event-type">Show event type</label>
                    </div>
                    <div class="form-group checkbox-group">
                        <input type="checkbox" id="show-score">
                        <label for="show-score">Show score</label>
                    </div>
                    <button class="btn btn-primary" onclick="exportClip()">Export for Social Media</button>
                    <div id="status"></div>
                </div>
            </div>

            <div class="sidebar">
                <div class="card">
                    <h2>Preview</h2>
                    <div class="preview-container" id="preview">
                        <div class="preview-placeholder">
                            <div class="icon">9:16</div>
                            <p>Select a clip to preview</p>
                        </div>
                    </div>
                    <p style="color: #64748b; font-size: 0.75rem; text-align: center;">
                        Vertical format optimized for mobile
                    </p>
                </div>
            </div>
        </div>
    </div>

    <script>
        let selectedClipIds = [];
        let selectedPlatform = 'tiktok';

        function selectPlatform(btn) {
            document.querySelectorAll('.platform-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            selectedPlatform = btn.textContent.toLowerCase();
        }

        async function loadClips() {
            try {
                // This would fetch from your clips API
                const response = await fetch('/api/clips?limit=50');
                const data = await response.json();

                const list = document.getElementById('clip-list');
                if (!data.clips || data.clips.length === 0) {
                    list.innerHTML = '<p style="color: #64748b; text-align: center; padding: 2rem;">No clips available</p>';
                    return;
                }

                list.innerHTML = data.clips.map(clip => `
                    <div class="clip-item" data-id="${clip.id}" onclick="toggleClip(this, ${clip.id})">
                        <div class="clip-thumb"></div>
                        <div class="clip-info">
                            <div class="clip-title">${clip.title || 'Untitled'}</div>
                            <div class="clip-meta">${clip.event_type || ''} - ${clip.duration || 0}s</div>
                        </div>
                    </div>
                `).join('');
            } catch (error) {
                document.getElementById('clip-list').innerHTML =
                    '<p style="color: #64748b; text-align: center; padding: 2rem;">No clips available yet. Record a game first!</p>';
            }
        }

        function toggleClip(element, clipId) {
            element.classList.toggle('selected');
            if (element.classList.contains('selected')) {
                selectedClipIds.push(clipId);
            } else {
                selectedClipIds = selectedClipIds.filter(id => id !== clipId);
            }
        }

        async function exportClip() {
            if (selectedClipIds.length === 0) {
                showStatus('Please select at least one clip', 'error');
                return;
            }

            showStatus('Processing...', 'processing');

            try {
                let result;

                if (selectedClipIds.length === 1) {
                    // Single clip export
                    const response = await fetch('/api/social/export', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            clip_id: selectedClipIds[0],
                            max_duration: parseInt(document.getElementById('max-duration').value),
                            show_score: document.getElementById('show-score').checked
                        })
                    });
                    result = await response.json();
                } else {
                    // Highlight reel
                    const response = await fetch('/api/social/highlight-reel', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            clip_ids: selectedClipIds
                        })
                    });
                    result = await response.json();
                }

                if (result.success) {
                    showStatus(`Export complete! <a href="${result.download_url}" style="color: inherit; font-weight: bold;">Download (${result.file_size_mb} MB)</a>`, 'success');

                    // Show video preview
                    document.getElementById('preview').innerHTML =
                        `<video controls src="${result.download_url}"></video>`;
                } else {
                    showStatus('Export failed: ' + result.error, 'error');
                }
            } catch (error) {
                showStatus('Export failed: ' + error.message, 'error');
            }
        }

        function showStatus(message, type) {
            const status = document.getElementById('status');
            status.innerHTML = message;
            status.className = 'status ' + type;
        }

        // Load clips on page load
        loadClips();
    </script>
</body>
</html>
"""
