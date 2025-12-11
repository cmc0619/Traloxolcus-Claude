"""
Soccer Rig Database Models

Schema Design:
- Parents can have multiple children
- Children (players) can be on multiple teams
- Teams have multiple seasons/sessions
- Games belong to teams and have recordings
- Events are detected in recordings and linked to players
- Stats are aggregated per player per game and per season

Birth year is used instead of age groups (U13, U14) for flexibility.
"""

from datetime import datetime, date
from typing import Optional, List
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, Date,
    Boolean, Float, ForeignKey, Table, Enum, UniqueConstraint, Index
)
from sqlalchemy.orm import declarative_base, relationship, backref
from sqlalchemy.dialects.postgresql import JSONB
from werkzeug.security import generate_password_hash, check_password_hash
import enum

Base = declarative_base()


# =============================================================================
# Enums
# =============================================================================

class UserRole(enum.Enum):
    PARENT = "parent"      # Parent/guardian - can view games, get notifications
    FAMILY = "family"      # Extended family (grandparent, etc.) - view access
    PLAYER = "player"      # Player - can view own stats/clips
    COACH = "coach"        # Coach - can view team stats, manage roster
    ADMIN = "admin"        # Admin - full access


class FeatureAccess(enum.Enum):
    """Feature flags for future feature-based auth."""
    STREAMING = "streaming"           # Can watch live game streams
    CLIPS = "clips"                   # Can view/download clips
    SOCIAL_EXPORT = "social_export"   # Can export to social media
    STATS = "stats"                   # Can view detailed statistics
    HEATMAPS = "heatmaps"             # Can view heat maps
    HIGHLIGHTS = "highlights"         # Can view auto-generated highlights


class PlayerPosition(enum.Enum):
    GOALKEEPER = "goalkeeper"
    DEFENDER = "defender"
    MIDFIELDER = "midfielder"
    FORWARD = "forward"
    UNKNOWN = "unknown"


class EventType(enum.Enum):
    GOAL = "goal"
    SHOT = "shot"
    SHOT_ON_TARGET = "shot_on_target"
    ASSIST = "assist"
    PASS = "pass"
    DRIBBLE = "dribble"
    TACKLE = "tackle"
    INTERCEPTION = "interception"
    SAVE = "save"
    SAVE_DIVING = "save_diving"
    SAVE_REFLEX = "save_reflex"
    PUNCH = "punch"
    CATCH = "catch"
    DISTRIBUTION = "distribution"
    GOAL_KICK = "goal_kick"
    FOUL = "foul"
    YELLOW_CARD = "yellow_card"
    RED_CARD = "red_card"


class NotificationFrequency(enum.Enum):
    INSTANT = "instant"
    DAILY = "daily"
    WEEKLY = "weekly"
    NONE = "none"


# =============================================================================
# Association Tables (Many-to-Many)
# =============================================================================

# Parents can have multiple children, children can have multiple parents/guardians
parent_player = Table(
    'parent_player',
    Base.metadata,
    Column('parent_id', Integer, ForeignKey('users.id'), primary_key=True),
    Column('player_id', Integer, ForeignKey('players.id'), primary_key=True),
    Column('relationship', String(50), default='parent'),  # parent, guardian, grandparent, family
    Column('created_at', DateTime, default=datetime.utcnow)
)

# Players can be on multiple teams (across seasons)
team_player = Table(
    'team_player',
    Base.metadata,
    Column('team_id', Integer, ForeignKey('teams.id'), primary_key=True),
    Column('player_id', Integer, ForeignKey('players.id'), primary_key=True),
    Column('jersey_number', String(10)),
    Column('position', String(50)),
    Column('is_active', Boolean, default=True),
    Column('joined_at', DateTime, default=datetime.utcnow)
)

# Coaches can manage multiple teams
team_coach = Table(
    'team_coach',
    Base.metadata,
    Column('team_id', Integer, ForeignKey('teams.id'), primary_key=True),
    Column('user_id', Integer, ForeignKey('users.id'), primary_key=True),
    Column('role', String(50), default='head_coach'),  # head_coach, assistant, manager
    Column('created_at', DateTime, default=datetime.utcnow)
)

# Users can follow multiple teams (direct team access without player link)
user_team = Table(
    'user_team',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id'), primary_key=True),
    Column('team_id', Integer, ForeignKey('teams.id'), primary_key=True),
    Column('role', String(50), default='follower'),  # follower, team_parent, manager
    Column('created_at', DateTime, default=datetime.utcnow)
)


# =============================================================================
# User Model (Parents, Coaches, Admins)
# =============================================================================

class User(Base):
    """
    User accounts for parents, coaches, and admins.
    Parents link to players through parent_player association.
    """
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    phone = Column(String(20))
    role = Column(Enum(UserRole), default=UserRole.PARENT)

    # Notification preferences
    notify_frequency = Column(Enum(NotificationFrequency), default=NotificationFrequency.INSTANT)
    notify_goals = Column(Boolean, default=True)
    notify_saves = Column(Boolean, default=True)
    notify_highlights = Column(Boolean, default=True)
    notify_game_ready = Column(Boolean, default=True)

    # TeamSnap integration
    teamsnap_token = Column(JSONB)  # OAuth token data (access_token, refresh_token, expires_at)
    teamsnap_user_id = Column(Integer)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime)

    # Relationships
    children = relationship('Player', secondary=parent_player, back_populates='parents')
    coached_teams = relationship('Team', secondary=team_coach, back_populates='coaches')
    followed_teams = relationship('Team', secondary=user_team, back_populates='followers')

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


# =============================================================================
# Player Model
# =============================================================================

class Player(Base):
    """
    Player (child) who appears in recordings.
    Uses birth_year instead of age groups for flexibility.
    Can be on multiple teams across different seasons.
    """
    __tablename__ = 'players'

    id = Column(Integer, primary_key=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    birth_year = Column(Integer, nullable=False, index=True)  # e.g., 2012, 2013
    birth_date = Column(Date)  # Optional full birth date

    # Default position (can vary by team)
    default_position = Column(Enum(PlayerPosition), default=PlayerPosition.UNKNOWN)

    # Photo for identification
    photo_url = Column(String(500))

    # TeamSnap link
    teamsnap_member_id = Column(Integer, index=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    parents = relationship('User', secondary=parent_player, back_populates='children')
    teams = relationship('Team', secondary=team_player, back_populates='players')
    events = relationship('GameEvent', back_populates='player')
    stats = relationship('PlayerGameStats', back_populates='player')

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def age(self) -> int:
        return date.today().year - self.birth_year

    def get_jersey_for_team(self, team_id: int) -> Optional[str]:
        """Get player's jersey number for a specific team."""
        from sqlalchemy import select
        # This would need session access - implement in service layer
        pass


# =============================================================================
# Organization & Team Models
# =============================================================================

class Organization(Base):
    """
    Club or organization that owns multiple teams.
    e.g., "Northside Soccer Club"
    """
    __tablename__ = 'organizations'

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    slug = Column(String(100), unique=True, index=True)  # URL-friendly name
    logo_url = Column(String(500))
    primary_color = Column(String(7))  # Hex color
    secondary_color = Column(String(7))

    # Contact
    email = Column(String(255))
    phone = Column(String(20))
    website = Column(String(255))

    # TeamSnap
    teamsnap_division_id = Column(Integer)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    teams = relationship('Team', back_populates='organization')


class Team(Base):
    """
    A team within an organization.
    Teams are seasonal - same group of kids may form new team each season.
    """
    __tablename__ = 'teams'

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey('organizations.id'))
    name = Column(String(200), nullable=False)  # e.g., "2012 Boys Blue"
    team_code = Column(String(20), unique=True, index=True)  # Access code for viewers

    # Age group by birth year range
    birth_year_start = Column(Integer)  # e.g., 2012
    birth_year_end = Column(Integer)    # e.g., 2012 (same for single year)

    # Season info
    season = Column(String(50))  # e.g., "Fall 2024", "Spring 2025"
    year = Column(Integer)

    # Team colors (override org if set)
    primary_color = Column(String(7))
    secondary_color = Column(String(7))

    # TeamSnap
    teamsnap_team_id = Column(Integer, index=True)
    teamsnap_last_sync = Column(DateTime)
    teamsnap_data = Column(JSONB)  # Raw API response for advanced queries

    # Status
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    organization = relationship('Organization', back_populates='teams')
    players = relationship('Player', secondary=team_player, back_populates='teams')
    coaches = relationship('User', secondary=team_coach, back_populates='coached_teams')
    followers = relationship('User', secondary=user_team, back_populates='followed_teams')
    games = relationship('Game', back_populates='team')

    @property
    def age_group(self) -> str:
        """Calculate age group like 'U13' from birth year."""
        if not self.birth_year_start:
            return "Unknown"
        current_year = date.today().year
        age = current_year - self.birth_year_start
        return f"U{age + 1}"


# =============================================================================
# Game & Recording Models
# =============================================================================

class Game(Base):
    """A recorded game/match."""
    __tablename__ = 'games'

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False, index=True)

    # Game info
    opponent = Column(String(200))
    location = Column(String(300))
    game_date = Column(DateTime, nullable=False, index=True)
    game_type = Column(String(50))  # league, tournament, friendly, practice

    # Score
    home_score = Column(Integer)
    away_score = Column(Integer)
    is_home = Column(Boolean, default=True)

    # Recording info
    session_id = Column(String(100), unique=True, index=True)  # From Pi nodes
    duration_seconds = Column(Integer)

    # Processing status
    is_processed = Column(Boolean, default=False)
    processed_at = Column(DateTime)
    panorama_url = Column(String(500))  # Stitched video URL
    thumbnail_url = Column(String(500))

    # Metadata from processing
    game_metadata = Column(JSONB)  # Flexible JSON for extra data

    # TeamSnap integration
    teamsnap_event_id = Column(Integer, index=True)  # TeamSnap event/game ID
    teamsnap_data = Column(JSONB)  # Raw TeamSnap API response

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    team = relationship('Team', back_populates='games')
    recordings = relationship('Recording', back_populates='game')
    events = relationship('GameEvent', back_populates='game')
    clips = relationship('Clip', back_populates='game')
    player_stats = relationship('PlayerGameStats', back_populates='game')


class Recording(Base):
    """Individual camera recording within a game."""
    __tablename__ = 'recordings'

    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey('games.id'), nullable=False, index=True)

    camera_id = Column(String(50), nullable=False)  # left, center, right
    camera_position = Column(Integer)  # 1, 2, 3

    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer)  # bytes
    duration_seconds = Column(Integer)
    resolution = Column(String(20))  # e.g., "3840x2160"
    fps = Column(Float)

    # Sync info
    sync_offset_ms = Column(Integer, default=0)  # Offset from reference camera

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    game = relationship('Game', back_populates='recordings')


# =============================================================================
# Event Models
# =============================================================================

class GameEvent(Base):
    """
    Detected event in a game (goal, shot, save, etc.).
    Linked to player when identified.
    """
    __tablename__ = 'game_events'

    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey('games.id'), nullable=False, index=True)
    player_id = Column(Integer, ForeignKey('players.id'), index=True)  # Nullable if unidentified

    event_type = Column(Enum(EventType), nullable=False, index=True)
    timestamp_seconds = Column(Float, nullable=False)  # Seconds from game start

    # Detection info
    confidence = Column(Float)  # ML confidence 0-1
    jersey_number = Column(String(10))  # Detected jersey, even if player not matched
    field_position_x = Column(Float)  # 0-1 normalized
    field_position_y = Column(Float)  # 0-1 normalized

    # Additional context
    description = Column(String(500))  # "Goal by #7 - Marcus Johnson"
    event_metadata = Column(JSONB)  # Extra data from ML

    # Verification
    is_verified = Column(Boolean, default=False)  # Coach verified
    verified_by = Column(Integer, ForeignKey('users.id'))

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    game = relationship('Game', back_populates='events')
    player = relationship('Player', back_populates='events')
    clips = relationship('Clip', back_populates='event')

    @property
    def display_time(self) -> str:
        """Format timestamp as MM:SS."""
        mins = int(self.timestamp_seconds // 60)
        secs = int(self.timestamp_seconds % 60)
        return f"{mins}:{secs:02d}"


# =============================================================================
# Clip Models
# =============================================================================

class Clip(Base):
    """Generated video clip from a game."""
    __tablename__ = 'clips'

    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey('games.id'), nullable=False, index=True)
    event_id = Column(Integer, ForeignKey('game_events.id'), index=True)  # Optional link to event

    title = Column(String(200), nullable=False)
    description = Column(Text)

    # Video info
    file_path = Column(String(500), nullable=False)
    thumbnail_url = Column(String(500))
    duration_seconds = Column(Float)
    start_time = Column(Float)  # Start time in source video
    end_time = Column(Float)

    # Type
    is_highlight = Column(Boolean, default=False)  # Part of auto-generated highlights
    is_public = Column(Boolean, default=True)  # Visible to all team parents

    # Stats
    view_count = Column(Integer, default=0)
    share_count = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(Integer, ForeignKey('users.id'))

    # Relationships
    game = relationship('Game', back_populates='clips')
    event = relationship('GameEvent', back_populates='clips')


# =============================================================================
# Statistics Models
# =============================================================================

class PlayerGameStats(Base):
    """Aggregated stats for a player in a single game."""
    __tablename__ = 'player_game_stats'
    __table_args__ = (
        UniqueConstraint('player_id', 'game_id', name='unique_player_game'),
    )

    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey('players.id'), nullable=False, index=True)
    game_id = Column(Integer, ForeignKey('games.id'), nullable=False, index=True)

    # Offensive stats
    goals = Column(Integer, default=0)
    assists = Column(Integer, default=0)
    shots = Column(Integer, default=0)
    shots_on_target = Column(Integer, default=0)

    # Possession stats
    passes = Column(Integer, default=0)
    pass_accuracy = Column(Float)  # Percentage
    dribbles = Column(Integer, default=0)
    dribble_success = Column(Float)

    # Defensive stats
    tackles = Column(Integer, default=0)
    interceptions = Column(Integer, default=0)
    fouls = Column(Integer, default=0)

    # Goalkeeper stats
    saves = Column(Integer, default=0)
    saves_diving = Column(Integer, default=0)
    goals_conceded = Column(Integer, default=0)
    save_percentage = Column(Float)
    punches = Column(Integer, default=0)
    catches = Column(Integer, default=0)

    # Cards
    yellow_cards = Column(Integer, default=0)
    red_cards = Column(Integer, default=0)

    # Playing time
    minutes_played = Column(Integer)

    # Calculated
    rating = Column(Float)  # Overall game rating if calculated

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    player = relationship('Player', back_populates='stats')
    game = relationship('Game', back_populates='player_stats')


class PlayerSeasonStats(Base):
    """Aggregated stats for a player across a season."""
    __tablename__ = 'player_season_stats'
    __table_args__ = (
        UniqueConstraint('player_id', 'team_id', 'season', name='unique_player_season'),
    )

    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey('players.id'), nullable=False, index=True)
    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False, index=True)
    season = Column(String(50), nullable=False)  # e.g., "Fall 2024"

    # Game counts
    games_played = Column(Integer, default=0)
    games_started = Column(Integer, default=0)
    minutes_played = Column(Integer, default=0)

    # Totals (same fields as game stats)
    goals = Column(Integer, default=0)
    assists = Column(Integer, default=0)
    shots = Column(Integer, default=0)
    shots_on_target = Column(Integer, default=0)
    passes = Column(Integer, default=0)
    dribbles = Column(Integer, default=0)
    tackles = Column(Integer, default=0)
    interceptions = Column(Integer, default=0)
    saves = Column(Integer, default=0)
    goals_conceded = Column(Integer, default=0)
    yellow_cards = Column(Integer, default=0)
    red_cards = Column(Integer, default=0)

    # Averages (calculated)
    goals_per_game = Column(Float)
    assists_per_game = Column(Float)
    save_percentage = Column(Float)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# =============================================================================
# Notification Models
# =============================================================================

class Notification(Base):
    """Notification queue for email/push."""
    __tablename__ = 'notifications'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    player_id = Column(Integer, ForeignKey('players.id'), index=True)  # Which child

    notification_type = Column(String(50), nullable=False)  # game_ready, new_clip, goal, etc.
    title = Column(String(200), nullable=False)
    body = Column(Text)
    data = Column(JSONB)  # Extra context

    # Delivery status
    is_sent = Column(Boolean, default=False)
    sent_at = Column(DateTime)
    is_read = Column(Boolean, default=False)
    read_at = Column(DateTime)

    # For digest mode
    digest_date = Column(Date)  # Group notifications by date

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_notifications_pending', 'user_id', 'is_sent'),
    )


# =============================================================================
# Database Initialization
# =============================================================================

def init_db(database_url: str):
    """Initialize database and create all tables."""
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    return engine


def get_engine(database_url: str):
    """Create SQLAlchemy engine from database URL."""
    return create_engine(database_url, pool_pre_ping=True)


def get_session(engine):
    """
    Create a scoped session factory.

    Returns a session that can be used as a context manager or directly.
    """
    from sqlalchemy.orm import sessionmaker, scoped_session
    session_factory = sessionmaker(bind=engine)
    return scoped_session(session_factory)
