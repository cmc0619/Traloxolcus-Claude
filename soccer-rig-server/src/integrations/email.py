"""
Email Notification Service for Soccer Rig

Sends notifications to parents when:
- Game processing is complete
- Their child has new clips (goals, saves, highlights)
- Weekly/daily digest summaries

Supports:
- SMTP (Gmail, SendGrid, etc.)
- Digest mode (batch notifications)
- Unsubscribe handling
- HTML email templates
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from datetime import datetime, date
from jinja2 import Environment, FileSystemLoader, select_autoescape
import threading
from queue import Queue

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class EmailConfig:
    """SMTP configuration."""
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    from_email: str = ""
    from_name: str = "Soccer Rig"
    use_tls: bool = True

    @classmethod
    def from_env(cls) -> 'EmailConfig':
        return cls(
            host=os.getenv('SMTP_HOST', 'smtp.gmail.com'),
            port=int(os.getenv('SMTP_PORT', '587')),
            username=os.getenv('SMTP_USER', ''),
            password=os.getenv('SMTP_PASS', ''),
            from_email=os.getenv('EMAIL_FROM', 'noreply@soccer-rig.local'),
            from_name=os.getenv('EMAIL_FROM_NAME', 'Soccer Rig'),
            use_tls=os.getenv('SMTP_TLS', 'true').lower() == 'true'
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.host and self.username and self.password)


# =============================================================================
# Email Templates
# =============================================================================

EMAIL_TEMPLATES = {
    'game_ready': {
        'subject': '⚽ {team_name} vs {opponent} - Game Ready!',
        'template': 'game_ready.html'
    },
    'new_clip': {
        'subject': '🎬 New clip: {player_name} - {event_type}!',
        'template': 'new_clip.html'
    },
    'goal': {
        'subject': '⚽ GOAL! {player_name} scored!',
        'template': 'goal.html'
    },
    'save': {
        'subject': '🧤 Great save by {player_name}!',
        'template': 'save.html'
    },
    'highlights': {
        'subject': '🌟 {player_name}\'s highlights are ready!',
        'template': 'highlights.html'
    },
    'digest': {
        'subject': '📊 Weekly Soccer Update for {player_name}',
        'template': 'digest.html'
    }
}


# Default HTML template (used if file templates not found)
DEFAULT_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%); color: white; padding: 30px; border-radius: 12px 12px 0 0; text-align: center; }
        .header h1 { margin: 0; font-size: 24px; }
        .content { background: #f8fafc; padding: 30px; border: 1px solid #e2e8f0; }
        .highlight { background: white; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #6366f1; }
        .button { display: inline-block; background: #6366f1; color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: 600; }
        .footer { text-align: center; padding: 20px; color: #64748b; font-size: 14px; }
        .footer a { color: #6366f1; }
    </style>
</head>
<body>
    <div class="header">
        <h1>⚽ {{ title }}</h1>
    </div>
    <div class="content">
        {{ content | safe }}

        {% if clip_url %}
        <div style="text-align: center; margin: 30px 0;">
            <a href="{{ clip_url }}" class="button">Watch Clip</a>
        </div>
        {% endif %}

        {% if view_url %}
        <div style="text-align: center; margin: 30px 0;">
            <a href="{{ view_url }}" class="button">View All Clips</a>
        </div>
        {% endif %}
    </div>
    <div class="footer">
        <p>You're receiving this because you're a registered parent on Soccer Rig.</p>
        <p><a href="{{ unsubscribe_url }}">Unsubscribe</a> | <a href="{{ preferences_url }}">Notification Preferences</a></p>
    </div>
</body>
</html>
"""


# =============================================================================
# Email Service
# =============================================================================

class EmailService:
    """
    Email notification service with async sending and templates.

    Usage:
        service = EmailService()

        # Send single email
        service.send_game_ready(
            to_email="parent@example.com",
            player_name="Marcus",
            team_name="2012 Boys Blue",
            opponent="Northside FC",
            game_url="https://viewer.soccer-rig.com/games/123"
        )

        # Queue for async sending
        service.queue_notification(
            notification_type="goal",
            to_email="parent@example.com",
            context={...}
        )
    """

    def __init__(self, config: Optional[EmailConfig] = None, template_dir: Optional[str] = None):
        self.config = config or EmailConfig.from_env()
        self.template_dir = template_dir

        # Setup Jinja2 for templates
        if template_dir and os.path.exists(template_dir):
            self.jinja_env = Environment(
                loader=FileSystemLoader(template_dir),
                autoescape=select_autoescape(['html', 'xml'])
            )
        else:
            self.jinja_env = Environment(autoescape=select_autoescape(['html', 'xml']))

        # Async queue
        self._queue: Queue = Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False

    @property
    def is_configured(self) -> bool:
        return self.config.is_configured

    def start_worker(self):
        """Start background worker for async sending."""
        if self._running:
            return

        self._running = True
        self._worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self._worker_thread.start()
        logger.info("Email worker started")

    def stop_worker(self):
        """Stop background worker."""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5)

    def _process_queue(self):
        """Process queued emails."""
        while self._running:
            try:
                if not self._queue.empty():
                    item = self._queue.get(timeout=1)
                    self._send_email(**item)
                    self._queue.task_done()
            except Exception as e:
                logger.error(f"Queue processing error: {e}")

    # -------------------------------------------------------------------------
    # Core Sending
    # -------------------------------------------------------------------------

    def _send_email(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None
    ) -> bool:
        """Send email via SMTP."""
        if not self.is_configured:
            logger.warning("Email not configured, skipping send")
            return False

        try:
            msg = MIMEMultipart('alternative')
            msg['From'] = formataddr((self.config.from_name, self.config.from_email))
            msg['To'] = to_email
            msg['Subject'] = subject

            # Plain text fallback
            if text_body:
                msg.attach(MIMEText(text_body, 'plain'))

            # HTML body
            msg.attach(MIMEText(html_body, 'html'))

            # Send
            with smtplib.SMTP(self.config.host, self.config.port) as server:
                if self.config.use_tls:
                    server.starttls()
                server.login(self.config.username, self.config.password)
                server.send_message(msg)

            logger.info(f"Email sent to {to_email}: {subject}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False

    def _render_template(
        self,
        notification_type: str,
        context: Dict[str, Any]
    ) -> tuple[str, str]:
        """Render email template and subject."""
        template_info = EMAIL_TEMPLATES.get(notification_type, {})

        # Render subject
        subject_template = template_info.get('subject', 'Soccer Rig Notification')
        subject = subject_template.format(**context)

        # Try file template first
        template_name = template_info.get('template')
        if template_name:
            try:
                template = self.jinja_env.get_template(template_name)
                html_body = template.render(**context)
                return subject, html_body
            except Exception:
                pass

        # Fall back to default template
        template = self.jinja_env.from_string(DEFAULT_TEMPLATE)
        html_body = template.render(**context)
        return subject, html_body

    def queue_notification(
        self,
        notification_type: str,
        to_email: str,
        context: Dict[str, Any]
    ):
        """Queue notification for async sending."""
        subject, html_body = self._render_template(notification_type, context)
        self._queue.put({
            'to_email': to_email,
            'subject': subject,
            'html_body': html_body
        })

    # -------------------------------------------------------------------------
    # Notification Types
    # -------------------------------------------------------------------------

    def send_game_ready(
        self,
        to_email: str,
        player_name: str,
        team_name: str,
        opponent: str,
        game_date: str,
        game_url: str,
        unsubscribe_url: str = "#",
        preferences_url: str = "#"
    ) -> bool:
        """Send 'game ready' notification."""
        subject, html = self._render_template('game_ready', {
            'title': 'Game Ready!',
            'content': f'''
                <p>Great news! The game footage is ready to view.</p>
                <div class="highlight">
                    <strong>{team_name}</strong> vs <strong>{opponent}</strong><br>
                    <span style="color: #64748b;">{game_date}</span>
                </div>
                <p>Check out {player_name}'s clips and highlights from the game!</p>
            ''',
            'view_url': game_url,
            'player_name': player_name,
            'team_name': team_name,
            'opponent': opponent,
            'unsubscribe_url': unsubscribe_url,
            'preferences_url': preferences_url
        })
        return self._send_email(to_email, subject, html)

    def send_goal_notification(
        self,
        to_email: str,
        player_name: str,
        team_name: str,
        opponent: str,
        minute: int,
        clip_url: str,
        thumbnail_url: Optional[str] = None,
        unsubscribe_url: str = "#",
        preferences_url: str = "#"
    ) -> bool:
        """Send goal notification."""
        subject, html = self._render_template('goal', {
            'title': f'{player_name} Scored!',
            'content': f'''
                <p>🎉 <strong>{player_name}</strong> scored a goal!</p>
                <div class="highlight">
                    <strong>{team_name}</strong> vs <strong>{opponent}</strong><br>
                    <span style="color: #64748b;">Minute {minute}</span>
                </div>
                <p>Watch the goal now!</p>
            ''',
            'clip_url': clip_url,
            'player_name': player_name,
            'team_name': team_name,
            'opponent': opponent,
            'event_type': 'Goal',
            'unsubscribe_url': unsubscribe_url,
            'preferences_url': preferences_url
        })
        return self._send_email(to_email, subject, html)

    def send_save_notification(
        self,
        to_email: str,
        player_name: str,
        team_name: str,
        opponent: str,
        minute: int,
        save_type: str,  # "diving save", "reflex save", etc.
        clip_url: str,
        unsubscribe_url: str = "#",
        preferences_url: str = "#"
    ) -> bool:
        """Send goalkeeper save notification."""
        subject, html = self._render_template('save', {
            'title': f'Great Save by {player_name}!',
            'content': f'''
                <p>🧤 <strong>{player_name}</strong> made an incredible {save_type}!</p>
                <div class="highlight">
                    <strong>{team_name}</strong> vs <strong>{opponent}</strong><br>
                    <span style="color: #64748b;">Minute {minute}</span>
                </div>
                <p>Watch the save now!</p>
            ''',
            'clip_url': clip_url,
            'player_name': player_name,
            'team_name': team_name,
            'opponent': opponent,
            'event_type': save_type.title(),
            'unsubscribe_url': unsubscribe_url,
            'preferences_url': preferences_url
        })
        return self._send_email(to_email, subject, html)

    def send_highlights_ready(
        self,
        to_email: str,
        player_name: str,
        team_name: str,
        game_count: int,
        highlights_url: str,
        stats_summary: Optional[Dict] = None,
        unsubscribe_url: str = "#",
        preferences_url: str = "#"
    ) -> bool:
        """Send highlights ready notification."""
        stats_html = ""
        if stats_summary:
            stats_html = f'''
                <div class="highlight">
                    <strong>Stats Summary</strong><br>
                    Goals: {stats_summary.get('goals', 0)} |
                    Assists: {stats_summary.get('assists', 0)} |
                    Saves: {stats_summary.get('saves', 0)}
                </div>
            '''

        subject, html = self._render_template('highlights', {
            'title': f'{player_name}\'s Highlights Ready!',
            'content': f'''
                <p>🌟 {player_name}'s highlight reel is ready!</p>
                {stats_html}
                <p>Watch the best moments from {game_count} game{"s" if game_count > 1 else ""}.</p>
            ''',
            'view_url': highlights_url,
            'player_name': player_name,
            'team_name': team_name,
            'unsubscribe_url': unsubscribe_url,
            'preferences_url': preferences_url
        })
        return self._send_email(to_email, subject, html)

    def send_digest(
        self,
        to_email: str,
        player_name: str,
        period: str,  # "week", "day"
        games: List[Dict],
        total_clips: int,
        highlights: List[Dict],
        view_url: str,
        unsubscribe_url: str = "#",
        preferences_url: str = "#"
    ) -> bool:
        """Send weekly/daily digest."""
        games_html = ""
        for game in games[:5]:  # Max 5 games
            games_html += f'''
                <div style="padding: 10px 0; border-bottom: 1px solid #e2e8f0;">
                    <strong>{game.get('opponent', 'Unknown')}</strong> - {game.get('date', '')}<br>
                    <span style="color: #64748b;">{game.get('clip_count', 0)} clips</span>
                </div>
            '''

        subject, html = self._render_template('digest', {
            'title': f'{player_name}\'s {period.title()}ly Update',
            'content': f'''
                <p>Here's what {player_name} was up to this {period}:</p>
                <div class="highlight">
                    <strong>{len(games)} Games</strong> | <strong>{total_clips} Clips</strong>
                </div>
                {games_html}
                <p>Check out all the clips and highlights!</p>
            ''',
            'view_url': view_url,
            'player_name': player_name,
            'unsubscribe_url': unsubscribe_url,
            'preferences_url': preferences_url
        })
        return self._send_email(to_email, subject, html)


# =============================================================================
# Notification Dispatcher
# =============================================================================

class NotificationDispatcher:
    """
    Dispatches notifications based on user preferences.

    Respects:
    - notify_frequency (instant, daily, weekly, none)
    - notify_goals, notify_saves, notify_highlights, notify_game_ready flags
    """

    def __init__(self, email_service: EmailService, db_session):
        self.email = email_service
        self.db = db_session

    def notify_event(
        self,
        event_type: str,
        player_id: int,
        game_id: int,
        context: Dict[str, Any]
    ):
        """
        Send notification for an event, respecting user preferences.

        Args:
            event_type: Type of event (goal, save, etc.)
            player_id: ID of the player involved
            game_id: ID of the game
            context: Additional context (clip_url, minute, etc.)
        """
        from .models import Player, User, Notification, NotificationFrequency

        # Get player and their parents
        player = self.db.query(Player).get(player_id)
        if not player:
            return

        for parent in player.parents:
            # Check if parent wants this notification type
            if not self._should_notify(parent, event_type):
                continue

            # Check frequency preference
            if parent.notify_frequency == NotificationFrequency.NONE:
                continue
            elif parent.notify_frequency == NotificationFrequency.INSTANT:
                # Send immediately
                self._send_event_notification(parent, player, event_type, context)
            else:
                # Queue for digest
                self._queue_for_digest(parent, player, event_type, game_id, context)

    def _should_notify(self, user, event_type: str) -> bool:
        """Check if user wants notifications for this event type."""
        if event_type in ('goal', 'assist'):
            return user.notify_goals
        elif event_type in ('save', 'save_diving', 'save_reflex'):
            return user.notify_saves
        elif event_type == 'highlight':
            return user.notify_highlights
        elif event_type == 'game_ready':
            return user.notify_game_ready
        return True  # Default to notify

    def _send_event_notification(self, user, player, event_type: str, context: Dict):
        """Send immediate notification."""
        base_url = os.getenv('VIEWER_URL', 'https://localhost')
        unsubscribe_url = f"{base_url}/unsubscribe/{user.id}"
        preferences_url = f"{base_url}/settings/notifications"

        if event_type == 'goal':
            self.email.send_goal_notification(
                to_email=user.email,
                player_name=player.first_name,
                team_name=context.get('team_name', ''),
                opponent=context.get('opponent', ''),
                minute=context.get('minute', 0),
                clip_url=context.get('clip_url', ''),
                unsubscribe_url=unsubscribe_url,
                preferences_url=preferences_url
            )
        elif event_type.startswith('save'):
            self.email.send_save_notification(
                to_email=user.email,
                player_name=player.first_name,
                team_name=context.get('team_name', ''),
                opponent=context.get('opponent', ''),
                minute=context.get('minute', 0),
                save_type=event_type.replace('_', ' '),
                clip_url=context.get('clip_url', ''),
                unsubscribe_url=unsubscribe_url,
                preferences_url=preferences_url
            )
        elif event_type == 'game_ready':
            self.email.send_game_ready(
                to_email=user.email,
                player_name=player.first_name,
                team_name=context.get('team_name', ''),
                opponent=context.get('opponent', ''),
                game_date=context.get('game_date', ''),
                game_url=context.get('game_url', ''),
                unsubscribe_url=unsubscribe_url,
                preferences_url=preferences_url
            )

    def _queue_for_digest(self, user, player, event_type: str, game_id: int, context: Dict):
        """Queue notification for daily/weekly digest."""
        from .models import Notification

        notification = Notification(
            user_id=user.id,
            player_id=player.id,
            notification_type=event_type,
            title=context.get('title', event_type),
            body=context.get('description', ''),
            data=context,
            digest_date=date.today()
        )
        self.db.add(notification)
        self.db.commit()

    def send_pending_digests(self):
        """Send all pending digest notifications (run via cron)."""
        from .models import User, Notification, NotificationFrequency
        from sqlalchemy import func

        # Get users with pending digest notifications
        users_with_pending = self.db.query(User).filter(
            User.notify_frequency.in_([NotificationFrequency.DAILY, NotificationFrequency.WEEKLY])
        ).all()

        for user in users_with_pending:
            pending = self.db.query(Notification).filter(
                Notification.user_id == user.id,
                Notification.is_sent == False
            ).all()

            if not pending:
                continue

            # Group by player
            by_player = {}
            for n in pending:
                if n.player_id not in by_player:
                    by_player[n.player_id] = []
                by_player[n.player_id].append(n)

            # Send digest for each player
            for player_id, notifications in by_player.items():
                self._send_digest_for_player(user, player_id, notifications)

    def _send_digest_for_player(self, user, player_id: int, notifications: List):
        """Compile and send digest for a specific player."""
        from .models import Player

        player = self.db.query(Player).get(player_id)
        if not player:
            return

        # Compile digest data
        games = {}
        for n in notifications:
            game_id = n.data.get('game_id')
            if game_id:
                if game_id not in games:
                    games[game_id] = {
                        'opponent': n.data.get('opponent', 'Unknown'),
                        'date': n.data.get('game_date', ''),
                        'clip_count': 0
                    }
                games[game_id]['clip_count'] += 1

        base_url = os.getenv('VIEWER_URL', 'https://localhost')

        self.email.send_digest(
            to_email=user.email,
            player_name=player.first_name,
            period='week' if user.notify_frequency.value == 'weekly' else 'day',
            games=list(games.values()),
            total_clips=len(notifications),
            highlights=[],
            view_url=f"{base_url}/players/{player_id}",
            unsubscribe_url=f"{base_url}/unsubscribe/{user.id}",
            preferences_url=f"{base_url}/settings/notifications"
        )

        # Mark as sent
        for n in notifications:
            n.is_sent = True
            n.sent_at = datetime.utcnow()
        self.db.commit()
