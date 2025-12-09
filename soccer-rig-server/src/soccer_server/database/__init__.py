"""
Database models for soccer video analytics.

Supports both PostgreSQL and MySQL via SQLAlchemy.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean,
    DateTime, Text, ForeignKey, JSON, Enum as SQLEnum, Index
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session
from sqlalchemy.pool import QueuePool

Base = declarative_base()


# =============================================================================
# Enums
# =============================================================================

class PlayerPosition(str, Enum):
    """Player positions."""
    GOALKEEPER = "goalkeeper"
    DEFENDER = "defender"
    MIDFIELDER = "midfielder"
    FORWARD = "forward"
    UNKNOWN = "unknown"


class EventType(str, Enum):
    """Types of trackable events."""
    # Ball events
    PASS = "pass"
    SHOT = "shot"
    CROSS = "cross"
    DRIBBLE = "dribble"
    TACKLE = "tackle"
    INTERCEPTION = "interception"
    CLEARANCE = "clearance"
    HEADER = "header"
    FOUL = "foul"

    # Movement events
    SPRINT = "sprint"
    MOVEMENT_OFF_BALL = "movement_off_ball"
    PRESSING = "pressing"
    TRACKING_BACK = "tracking_back"

    # Goalkeeper events
    GK_SAVE = "gk_save"
    GK_SAVE_DIVING = "gk_save_diving"
    GK_SAVE_REFLEX = "gk_save_reflex"
    GK_PUNCH = "gk_punch"
    GK_CATCH = "gk_catch"
    GK_PARRY = "gk_parry"
    GK_DISTRIBUTION_THROW = "gk_distribution_throw"
    GK_DISTRIBUTION_KICK = "gk_distribution_kick"
    GK_GOAL_KICK = "gk_goal_kick"
    GK_SWEEP = "gk_sweep"
    GK_POSITIONING = "gk_positioning"
    GK_COMING_OUT = "gk_coming_out"
    GK_ONE_ON_ONE = "gk_one_on_one"

    # Set pieces
    CORNER_KICK = "corner_kick"
    FREE_KICK = "free_kick"
    THROW_IN = "throw_in"
    PENALTY = "penalty"

    # Goals
    GOAL = "goal"
    OWN_GOAL = "own_goal"

    # Other
    SUBSTITUTION = "substitution"
    YELLOW_CARD = "yellow_card"
    RED_CARD = "red_card"
    OFFSIDE = "offside"


class EventOutcome(str, Enum):
    """Outcome of an event."""
    SUCCESS = "success"
    FAILURE = "failure"
    BLOCKED = "blocked"
    SAVED = "saved"
    OFF_TARGET = "off_target"
    ON_TARGET = "on_target"
    GOAL = "goal"
    NEUTRAL = "neutral"


# =============================================================================
# Models
# =============================================================================

class Game(Base):
    """A recorded game/session."""
    __tablename__ = "games"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(100), unique=True, nullable=False, index=True)

    # Game info
    title = Column(String(200))
    date = Column(DateTime, nullable=False)
    location = Column(String(200))
    home_team = Column(String(100))
    away_team = Column(String(100))

    # Video info
    duration_sec = Column(Float)
    panorama_path = Column(String(500))
    is_processed = Column(Boolean, default=False)
    is_analyzed = Column(Boolean, default=False)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    metadata_json = Column(JSON)

    # Relationships
    players = relationship("Player", back_populates="game", cascade="all, delete-orphan")
    events = relationship("Event", back_populates="game", cascade="all, delete-orphan")
    tracks = relationship("PlayerTrack", back_populates="game", cascade="all, delete-orphan")
    clips = relationship("Clip", back_populates="game", cascade="all, delete-orphan")


class Player(Base):
    """A player in a game."""
    __tablename__ = "players"

    id = Column(Integer, primary_key=True, autoincrement=True)
    game_id = Column(Integer, ForeignKey("games.id", ondelete="CASCADE"), nullable=False)

    # Player info
    name = Column(String(100))
    jersey_number = Column(Integer)
    team = Column(String(100))  # "home" or "away" or team name
    position = Column(SQLEnum(PlayerPosition), default=PlayerPosition.UNKNOWN)
    is_goalkeeper = Column(Boolean, default=False)

    # Tracking ID (for linking detections)
    tracking_id = Column(String(50))

    # Stats summary (updated after analysis)
    total_events = Column(Integer, default=0)
    total_distance_m = Column(Float, default=0)
    max_speed_kmh = Column(Float, default=0)
    avg_speed_kmh = Column(Float, default=0)

    # Relationships
    game = relationship("Game", back_populates="players")
    events = relationship("Event", back_populates="player", cascade="all, delete-orphan")
    tracks = relationship("PlayerTrack", back_populates="player", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_player_game_jersey", "game_id", "jersey_number"),
    )


class Event(Base):
    """A single event/action in the game."""
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    game_id = Column(Integer, ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    player_id = Column(Integer, ForeignKey("players.id", ondelete="SET NULL"), nullable=True)

    # Event type and timing
    event_type = Column(SQLEnum(EventType), nullable=False, index=True)
    timestamp_sec = Column(Float, nullable=False, index=True)  # Video timestamp
    duration_sec = Column(Float)  # Duration of event (e.g., sprint duration)

    # Outcome
    outcome = Column(SQLEnum(EventOutcome))

    # Location on field (normalized 0-1)
    x = Column(Float)
    y = Column(Float)
    end_x = Column(Float)  # For passes, shots, etc.
    end_y = Column(Float)

    # Video frame info
    frame_number = Column(Integer)

    # Confidence and source
    confidence = Column(Float, default=1.0)  # ML confidence score
    is_manual = Column(Boolean, default=False)  # Manual annotation vs auto-detected

    # Additional data
    description = Column(Text)
    tags = Column(JSON)  # ["important", "highlight", etc.]
    metadata_json = Column(JSON)

    # Relationships
    game = relationship("Game", back_populates="events")
    player = relationship("Player", back_populates="events")

    __table_args__ = (
        Index("ix_event_game_time", "game_id", "timestamp_sec"),
        Index("ix_event_type_game", "event_type", "game_id"),
    )


class PlayerTrack(Base):
    """Player position tracking data (sampled)."""
    __tablename__ = "player_tracks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    game_id = Column(Integer, ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    player_id = Column(Integer, ForeignKey("players.id", ondelete="SET NULL"), nullable=True)

    # Timing
    timestamp_sec = Column(Float, nullable=False)
    frame_number = Column(Integer)

    # Position (normalized 0-1 on field)
    x = Column(Float, nullable=False)
    y = Column(Float, nullable=False)

    # Velocity
    speed_kmh = Column(Float)
    direction_deg = Column(Float)  # 0-360

    # Bounding box in frame (pixels)
    bbox_x = Column(Integer)
    bbox_y = Column(Integer)
    bbox_w = Column(Integer)
    bbox_h = Column(Integer)

    # Detection confidence
    confidence = Column(Float)

    # Relationships
    game = relationship("Game", back_populates="tracks")
    player = relationship("Player", back_populates="tracks")

    __table_args__ = (
        Index("ix_track_game_time", "game_id", "timestamp_sec"),
        Index("ix_track_player_time", "player_id", "timestamp_sec"),
    )


class Clip(Base):
    """Generated video clips for specific events/players."""
    __tablename__ = "clips"

    id = Column(Integer, primary_key=True, autoincrement=True)
    game_id = Column(Integer, ForeignKey("games.id", ondelete="CASCADE"), nullable=False)

    # Clip info
    title = Column(String(200))
    description = Column(Text)

    # Time range
    start_sec = Column(Float, nullable=False)
    end_sec = Column(Float, nullable=False)

    # File info
    file_path = Column(String(500))
    file_size_bytes = Column(Integer)
    thumbnail_path = Column(String(500))

    # Type
    clip_type = Column(String(50))  # "event", "player_highlight", "custom"

    # Related entities
    player_ids = Column(JSON)  # List of player IDs featured
    event_ids = Column(JSON)  # List of event IDs included

    # Generation info
    is_generated = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    game = relationship("Game", back_populates="clips")


class QueryLog(Base):
    """Log of natural language queries."""
    __tablename__ = "query_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Query
    natural_query = Column(Text, nullable=False)
    generated_sql = Column(Text)

    # Results
    result_count = Column(Integer)
    execution_time_ms = Column(Float)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    user_ip = Column(String(50))


# =============================================================================
# Database Manager
# =============================================================================

class DatabaseManager:
    """Manages database connections and operations."""

    def __init__(self, connection_url: str):
        """
        Initialize database manager.

        Args:
            connection_url: SQLAlchemy connection URL
                PostgreSQL: postgresql://user:pass@host:5432/dbname
                MySQL: mysql+pymysql://user:pass@host:3306/dbname
        """
        self.connection_url = connection_url
        self.engine = create_engine(
            connection_url,
            poolclass=QueuePool,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
        )
        self.SessionLocal = sessionmaker(bind=self.engine)

    def create_tables(self) -> None:
        """Create all tables."""
        Base.metadata.create_all(self.engine)

    def drop_tables(self) -> None:
        """Drop all tables (use with caution!)."""
        Base.metadata.drop_all(self.engine)

    def get_session(self) -> Session:
        """Get a database session."""
        return self.SessionLocal()

    # -------------------------------------------------------------------------
    # Game operations
    # -------------------------------------------------------------------------

    def create_game(self, session_id: str, **kwargs) -> Game:
        """Create a new game record."""
        with self.get_session() as session:
            game = Game(session_id=session_id, **kwargs)
            session.add(game)
            session.commit()
            session.refresh(game)
            return game

    def get_game(self, session_id: str) -> Optional[Game]:
        """Get game by session ID."""
        with self.get_session() as session:
            return session.query(Game).filter(Game.session_id == session_id).first()

    def get_game_by_id(self, game_id: int) -> Optional[Game]:
        """Get game by ID."""
        with self.get_session() as session:
            return session.query(Game).filter(Game.id == game_id).first()

    def list_games(self, limit: int = 50, offset: int = 0) -> List[Game]:
        """List all games."""
        with self.get_session() as session:
            return session.query(Game).order_by(Game.date.desc()).offset(offset).limit(limit).all()

    # -------------------------------------------------------------------------
    # Player operations
    # -------------------------------------------------------------------------

    def add_player(self, game_id: int, **kwargs) -> Player:
        """Add a player to a game."""
        with self.get_session() as session:
            player = Player(game_id=game_id, **kwargs)
            session.add(player)
            session.commit()
            session.refresh(player)
            return player

    def get_player(self, game_id: int, jersey_number: int) -> Optional[Player]:
        """Get player by jersey number."""
        with self.get_session() as session:
            return session.query(Player).filter(
                Player.game_id == game_id,
                Player.jersey_number == jersey_number
            ).first()

    def get_players_by_game(self, game_id: int) -> List[Player]:
        """Get all players in a game."""
        with self.get_session() as session:
            return session.query(Player).filter(Player.game_id == game_id).all()

    # -------------------------------------------------------------------------
    # Event operations
    # -------------------------------------------------------------------------

    def log_event(
        self,
        game_id: int,
        event_type: EventType,
        timestamp_sec: float,
        player_id: Optional[int] = None,
        **kwargs
    ) -> Event:
        """Log a game event."""
        with self.get_session() as session:
            event = Event(
                game_id=game_id,
                player_id=player_id,
                event_type=event_type,
                timestamp_sec=timestamp_sec,
                **kwargs
            )
            session.add(event)
            session.commit()
            session.refresh(event)
            return event

    def get_events(
        self,
        game_id: int,
        event_type: Optional[EventType] = None,
        player_id: Optional[int] = None,
        start_sec: Optional[float] = None,
        end_sec: Optional[float] = None,
    ) -> List[Event]:
        """Query events with filters."""
        with self.get_session() as session:
            query = session.query(Event).filter(Event.game_id == game_id)

            if event_type:
                query = query.filter(Event.event_type == event_type)
            if player_id:
                query = query.filter(Event.player_id == player_id)
            if start_sec is not None:
                query = query.filter(Event.timestamp_sec >= start_sec)
            if end_sec is not None:
                query = query.filter(Event.timestamp_sec <= end_sec)

            return query.order_by(Event.timestamp_sec).all()

    def get_player_events(self, player_id: int) -> List[Event]:
        """Get all events for a player."""
        with self.get_session() as session:
            return session.query(Event).filter(
                Event.player_id == player_id
            ).order_by(Event.timestamp_sec).all()

    def get_gk_events(self, game_id: int) -> List[Event]:
        """Get all goalkeeper events for a game."""
        gk_types = [
            EventType.GK_SAVE, EventType.GK_SAVE_DIVING, EventType.GK_SAVE_REFLEX,
            EventType.GK_PUNCH, EventType.GK_CATCH, EventType.GK_PARRY,
            EventType.GK_DISTRIBUTION_THROW, EventType.GK_DISTRIBUTION_KICK,
            EventType.GK_GOAL_KICK, EventType.GK_SWEEP, EventType.GK_POSITIONING,
            EventType.GK_COMING_OUT, EventType.GK_ONE_ON_ONE,
        ]
        with self.get_session() as session:
            return session.query(Event).filter(
                Event.game_id == game_id,
                Event.event_type.in_(gk_types)
            ).order_by(Event.timestamp_sec).all()

    # -------------------------------------------------------------------------
    # Track operations
    # -------------------------------------------------------------------------

    def log_track(
        self,
        game_id: int,
        timestamp_sec: float,
        x: float,
        y: float,
        player_id: Optional[int] = None,
        **kwargs
    ) -> PlayerTrack:
        """Log a player position."""
        with self.get_session() as session:
            track = PlayerTrack(
                game_id=game_id,
                player_id=player_id,
                timestamp_sec=timestamp_sec,
                x=x,
                y=y,
                **kwargs
            )
            session.add(track)
            session.commit()
            return track

    def bulk_log_tracks(self, tracks: List[Dict[str, Any]]) -> int:
        """Bulk insert track data."""
        with self.get_session() as session:
            session.bulk_insert_mappings(PlayerTrack, tracks)
            session.commit()
            return len(tracks)

    def get_player_tracks(
        self,
        player_id: int,
        start_sec: Optional[float] = None,
        end_sec: Optional[float] = None,
    ) -> List[PlayerTrack]:
        """Get tracking data for a player."""
        with self.get_session() as session:
            query = session.query(PlayerTrack).filter(PlayerTrack.player_id == player_id)

            if start_sec is not None:
                query = query.filter(PlayerTrack.timestamp_sec >= start_sec)
            if end_sec is not None:
                query = query.filter(PlayerTrack.timestamp_sec <= end_sec)

            return query.order_by(PlayerTrack.timestamp_sec).all()

    # -------------------------------------------------------------------------
    # Clip operations
    # -------------------------------------------------------------------------

    def create_clip(
        self,
        game_id: int,
        start_sec: float,
        end_sec: float,
        **kwargs
    ) -> Clip:
        """Create a clip record."""
        with self.get_session() as session:
            clip = Clip(
                game_id=game_id,
                start_sec=start_sec,
                end_sec=end_sec,
                **kwargs
            )
            session.add(clip)
            session.commit()
            session.refresh(clip)
            return clip

    def get_clips(self, game_id: int) -> List[Clip]:
        """Get all clips for a game."""
        with self.get_session() as session:
            return session.query(Clip).filter(Clip.game_id == game_id).all()

    def get_player_clips(self, player_id: int) -> List[Clip]:
        """Get clips featuring a player."""
        with self.get_session() as session:
            return session.query(Clip).filter(
                Clip.player_ids.contains([player_id])
            ).all()

    # -------------------------------------------------------------------------
    # Query logging
    # -------------------------------------------------------------------------

    def log_query(self, natural_query: str, **kwargs) -> QueryLog:
        """Log a natural language query."""
        with self.get_session() as session:
            log = QueryLog(natural_query=natural_query, **kwargs)
            session.add(log)
            session.commit()
            return log
