"""
Natural language query interface for soccer video analytics.

Allows users to query events and generate clips using natural language:
- "Show me all saves by the goalkeeper"
- "Find passes in the first half"
- "Get #7's dribbles near the box"
- "Show goals from last game"
"""

import re
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum

from soccer_server.database import (
    DatabaseManager, EventType, EventOutcome, PlayerPosition,
    Event, Player, Game
)

logger = logging.getLogger(__name__)


# =============================================================================
# Query Parser
# =============================================================================

@dataclass
class ParsedQuery:
    """Parsed natural language query."""
    event_types: List[EventType]
    player_filter: Optional[Dict[str, Any]]  # jersey_number, position, name
    time_filter: Optional[Dict[str, Any]]  # start_sec, end_sec, period
    location_filter: Optional[Dict[str, Any]]  # area of field
    outcome_filter: Optional[EventOutcome]
    limit: int = 50
    include_clips: bool = False


class QueryParser:
    """Parses natural language queries into structured filters."""

    # Event type keywords
    EVENT_KEYWORDS = {
        # Ball events
        "pass": [EventType.PASS],
        "passes": [EventType.PASS],
        "passing": [EventType.PASS],
        "shot": [EventType.SHOT],
        "shots": [EventType.SHOT],
        "shooting": [EventType.SHOT],
        "cross": [EventType.CROSS],
        "crosses": [EventType.CROSS],
        "dribble": [EventType.DRIBBLE],
        "dribbles": [EventType.DRIBBLE],
        "dribbling": [EventType.DRIBBLE],
        "tackle": [EventType.TACKLE],
        "tackles": [EventType.TACKLE],
        "tackling": [EventType.TACKLE],
        "interception": [EventType.INTERCEPTION],
        "interceptions": [EventType.INTERCEPTION],
        "clearance": [EventType.CLEARANCE],
        "clearances": [EventType.CLEARANCE],
        "header": [EventType.HEADER],
        "headers": [EventType.HEADER],

        # Goals
        "goal": [EventType.GOAL],
        "goals": [EventType.GOAL],
        "scored": [EventType.GOAL],

        # Movement
        "sprint": [EventType.SPRINT],
        "sprints": [EventType.SPRINT],
        "sprinting": [EventType.SPRINT],
        "run": [EventType.SPRINT],
        "runs": [EventType.SPRINT],
        "running": [EventType.SPRINT],
        "movement": [EventType.MOVEMENT_OFF_BALL],
        "off the ball": [EventType.MOVEMENT_OFF_BALL],
        "pressing": [EventType.PRESSING],
        "press": [EventType.PRESSING],

        # Goalkeeper
        "save": [EventType.GK_SAVE, EventType.GK_SAVE_DIVING, EventType.GK_SAVE_REFLEX],
        "saves": [EventType.GK_SAVE, EventType.GK_SAVE_DIVING, EventType.GK_SAVE_REFLEX],
        "diving save": [EventType.GK_SAVE_DIVING],
        "reflex save": [EventType.GK_SAVE_REFLEX],
        "punch": [EventType.GK_PUNCH],
        "punches": [EventType.GK_PUNCH],
        "punching": [EventType.GK_PUNCH],
        "catch": [EventType.GK_CATCH],
        "catches": [EventType.GK_CATCH],
        "catching": [EventType.GK_CATCH],
        "parry": [EventType.GK_PARRY],
        "parries": [EventType.GK_PARRY],
        "distribution": [EventType.GK_DISTRIBUTION_THROW, EventType.GK_DISTRIBUTION_KICK],
        "throw": [EventType.GK_DISTRIBUTION_THROW],
        "throws": [EventType.GK_DISTRIBUTION_THROW],
        "goal kick": [EventType.GK_GOAL_KICK],
        "goal kicks": [EventType.GK_GOAL_KICK],
        "sweep": [EventType.GK_SWEEP],
        "sweeper": [EventType.GK_SWEEP],
        "coming out": [EventType.GK_COMING_OUT],
        "one on one": [EventType.GK_ONE_ON_ONE],
        "1v1": [EventType.GK_ONE_ON_ONE],

        # Set pieces
        "corner": [EventType.CORNER_KICK],
        "corners": [EventType.CORNER_KICK],
        "free kick": [EventType.FREE_KICK],
        "free kicks": [EventType.FREE_KICK],
        "penalty": [EventType.PENALTY],
        "penalties": [EventType.PENALTY],

        # Cards
        "yellow card": [EventType.YELLOW_CARD],
        "yellow": [EventType.YELLOW_CARD],
        "red card": [EventType.RED_CARD],
        "red": [EventType.RED_CARD],
        "card": [EventType.YELLOW_CARD, EventType.RED_CARD],
        "cards": [EventType.YELLOW_CARD, EventType.RED_CARD],
    }

    # Position keywords
    POSITION_KEYWORDS = {
        "goalkeeper": PlayerPosition.GOALKEEPER,
        "goalie": PlayerPosition.GOALKEEPER,
        "keeper": PlayerPosition.GOALKEEPER,
        "gk": PlayerPosition.GOALKEEPER,
        "defender": PlayerPosition.DEFENDER,
        "defenders": PlayerPosition.DEFENDER,
        "defense": PlayerPosition.DEFENDER,
        "midfielder": PlayerPosition.MIDFIELDER,
        "midfielders": PlayerPosition.MIDFIELDER,
        "midfield": PlayerPosition.MIDFIELDER,
        "forward": PlayerPosition.FORWARD,
        "forwards": PlayerPosition.FORWARD,
        "striker": PlayerPosition.FORWARD,
        "strikers": PlayerPosition.FORWARD,
        "attacker": PlayerPosition.FORWARD,
        "attackers": PlayerPosition.FORWARD,
    }

    # Time period keywords
    TIME_KEYWORDS = {
        "first half": (0, 45 * 60),
        "1st half": (0, 45 * 60),
        "second half": (45 * 60, 90 * 60),
        "2nd half": (45 * 60, 90 * 60),
        "first 15": (0, 15 * 60),
        "last 15": (75 * 60, 90 * 60),
        "first 30": (0, 30 * 60),
        "last 30": (60 * 60, 90 * 60),
        "opening": (0, 10 * 60),
        "closing": (80 * 60, 90 * 60),
    }

    # Outcome keywords
    OUTCOME_KEYWORDS = {
        "successful": EventOutcome.SUCCESS,
        "success": EventOutcome.SUCCESS,
        "completed": EventOutcome.SUCCESS,
        "failed": EventOutcome.FAILURE,
        "unsuccessful": EventOutcome.FAILURE,
        "missed": EventOutcome.FAILURE,
        "blocked": EventOutcome.BLOCKED,
        "saved": EventOutcome.SAVED,
        "on target": EventOutcome.ON_TARGET,
        "off target": EventOutcome.OFF_TARGET,
    }

    # Location keywords
    LOCATION_KEYWORDS = {
        "box": {"area": "penalty_area"},
        "penalty area": {"area": "penalty_area"},
        "penalty box": {"area": "penalty_area"},
        "six yard box": {"area": "six_yard"},
        "midfield": {"area": "midfield"},
        "left wing": {"area": "left_wing"},
        "right wing": {"area": "right_wing"},
        "near post": {"area": "near_post"},
        "far post": {"area": "far_post"},
    }

    def parse(self, query: str) -> ParsedQuery:
        """
        Parse a natural language query.

        Args:
            query: Natural language query string

        Returns:
            ParsedQuery with extracted filters
        """
        query_lower = query.lower().strip()

        # Extract event types
        event_types = self._extract_event_types(query_lower)

        # Extract player filter
        player_filter = self._extract_player_filter(query_lower)

        # Extract time filter
        time_filter = self._extract_time_filter(query_lower)

        # Extract location filter
        location_filter = self._extract_location_filter(query_lower)

        # Extract outcome filter
        outcome_filter = self._extract_outcome_filter(query_lower)

        # Check for clip request
        include_clips = any(word in query_lower for word in [
            "clip", "clips", "video", "show me", "watch", "see"
        ])

        # Extract limit if specified
        limit = self._extract_limit(query_lower)

        return ParsedQuery(
            event_types=event_types,
            player_filter=player_filter,
            time_filter=time_filter,
            location_filter=location_filter,
            outcome_filter=outcome_filter,
            limit=limit,
            include_clips=include_clips,
        )

    def _extract_event_types(self, query: str) -> List[EventType]:
        """Extract event types from query."""
        event_types = []

        # Check for multi-word keywords first (longer matches take priority)
        sorted_keywords = sorted(self.EVENT_KEYWORDS.keys(), key=len, reverse=True)

        for keyword in sorted_keywords:
            if keyword in query:
                event_types.extend(self.EVENT_KEYWORDS[keyword])
                break  # Take first match

        # If "all" or "everything" or no specific type, return empty (all types)
        if not event_types and any(word in query for word in ["all", "everything", "any"]):
            return []

        return list(set(event_types))

    def _extract_player_filter(self, query: str) -> Optional[Dict[str, Any]]:
        """Extract player filter from query."""
        player_filter = {}

        # Check for jersey number (#7, number 7, player 7)
        jersey_match = re.search(r'#(\d+)|number\s*(\d+)|player\s*(\d+)', query)
        if jersey_match:
            number = jersey_match.group(1) or jersey_match.group(2) or jersey_match.group(3)
            player_filter["jersey_number"] = int(number)

        # Check for position
        for keyword, position in self.POSITION_KEYWORDS.items():
            if keyword in query:
                player_filter["position"] = position
                break

        # Check for team
        if "home" in query:
            player_filter["team"] = "home"
        elif "away" in query:
            player_filter["team"] = "away"

        return player_filter if player_filter else None

    def _extract_time_filter(self, query: str) -> Optional[Dict[str, Any]]:
        """Extract time filter from query."""
        time_filter = {}

        # Check for period keywords
        for keyword, (start, end) in self.TIME_KEYWORDS.items():
            if keyword in query:
                time_filter["start_sec"] = start
                time_filter["end_sec"] = end
                return time_filter

        # Check for minute ranges (e.g., "between 20 and 30 minutes")
        range_match = re.search(r'between\s*(\d+)\s*and\s*(\d+)\s*min', query)
        if range_match:
            time_filter["start_sec"] = int(range_match.group(1)) * 60
            time_filter["end_sec"] = int(range_match.group(2)) * 60
            return time_filter

        # Check for after/before (e.g., "after 60 minutes")
        after_match = re.search(r'after\s*(\d+)\s*min', query)
        if after_match:
            time_filter["start_sec"] = int(after_match.group(1)) * 60
            return time_filter

        before_match = re.search(r'before\s*(\d+)\s*min', query)
        if before_match:
            time_filter["end_sec"] = int(before_match.group(1)) * 60
            return time_filter

        return time_filter if time_filter else None

    def _extract_location_filter(self, query: str) -> Optional[Dict[str, Any]]:
        """Extract location filter from query."""
        for keyword, location in self.LOCATION_KEYWORDS.items():
            if keyword in query:
                return location
        return None

    def _extract_outcome_filter(self, query: str) -> Optional[EventOutcome]:
        """Extract outcome filter from query."""
        for keyword, outcome in self.OUTCOME_KEYWORDS.items():
            if keyword in query:
                return outcome
        return None

    def _extract_limit(self, query: str) -> int:
        """Extract result limit from query."""
        # Check for "top N" or "first N" or just a number
        limit_match = re.search(r'top\s*(\d+)|first\s*(\d+)|last\s*(\d+)|(\d+)\s*results', query)
        if limit_match:
            for group in limit_match.groups():
                if group:
                    return min(int(group), 100)
        return 50


# =============================================================================
# Query Executor
# =============================================================================

class QueryExecutor:
    """Executes parsed queries against the database."""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def execute(
        self,
        parsed_query: ParsedQuery,
        game_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute a parsed query.

        Args:
            parsed_query: Parsed query object
            game_id: Optional game ID to filter by

        Returns:
            Query results
        """
        start_time = datetime.now()

        with self.db.get_session() as session:
            # Build query
            query = session.query(Event)

            # Filter by game
            if game_id:
                query = query.filter(Event.game_id == game_id)

            # Filter by event type
            if parsed_query.event_types:
                query = query.filter(Event.event_type.in_(parsed_query.event_types))

            # Filter by time
            if parsed_query.time_filter:
                if "start_sec" in parsed_query.time_filter:
                    query = query.filter(
                        Event.timestamp_sec >= parsed_query.time_filter["start_sec"]
                    )
                if "end_sec" in parsed_query.time_filter:
                    query = query.filter(
                        Event.timestamp_sec <= parsed_query.time_filter["end_sec"]
                    )

            # Filter by outcome
            if parsed_query.outcome_filter:
                query = query.filter(Event.outcome == parsed_query.outcome_filter)

            # Filter by player
            if parsed_query.player_filter:
                player_subquery = session.query(Player.id)

                if "jersey_number" in parsed_query.player_filter:
                    player_subquery = player_subquery.filter(
                        Player.jersey_number == parsed_query.player_filter["jersey_number"]
                    )
                if "position" in parsed_query.player_filter:
                    player_subquery = player_subquery.filter(
                        Player.position == parsed_query.player_filter["position"]
                    )
                if "team" in parsed_query.player_filter:
                    player_subquery = player_subquery.filter(
                        Player.team == parsed_query.player_filter["team"]
                    )

                query = query.filter(Event.player_id.in_(player_subquery))

            # Order and limit
            query = query.order_by(Event.timestamp_sec)
            query = query.limit(parsed_query.limit)

            # Execute
            events = query.all()

            # Calculate execution time
            execution_time_ms = (datetime.now() - start_time).total_seconds() * 1000

            # Format results
            results = []
            for event in events:
                result = {
                    "id": event.id,
                    "event_type": event.event_type.value,
                    "timestamp_sec": event.timestamp_sec,
                    "timestamp_formatted": self._format_timestamp(event.timestamp_sec),
                    "outcome": event.outcome.value if event.outcome else None,
                    "confidence": event.confidence,
                    "x": event.x,
                    "y": event.y,
                    "description": event.description,
                }

                # Add player info if available
                if event.player:
                    result["player"] = {
                        "id": event.player.id,
                        "name": event.player.name,
                        "jersey_number": event.player.jersey_number,
                        "team": event.player.team,
                    }

                results.append(result)

            return {
                "success": True,
                "count": len(results),
                "events": results,
                "execution_time_ms": execution_time_ms,
                "include_clips": parsed_query.include_clips,
            }

    def _format_timestamp(self, seconds: float) -> str:
        """Format timestamp as MM:SS."""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}:{secs:02d}"


# =============================================================================
# Natural Language Interface
# =============================================================================

class NaturalLanguageQuery:
    """
    High-level interface for natural language queries.

    Example usage:
        nlq = NaturalLanguageQuery(db_manager)
        results = nlq.query("Show me all saves by the goalkeeper in the first half")
    """

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self.parser = QueryParser()
        self.executor = QueryExecutor(db_manager)

    def query(
        self,
        natural_query: str,
        game_id: Optional[int] = None,
        log_query: bool = True,
    ) -> Dict[str, Any]:
        """
        Execute a natural language query.

        Args:
            natural_query: Natural language query string
            game_id: Optional game ID to filter by
            log_query: Whether to log the query

        Returns:
            Query results
        """
        logger.info(f"Processing query: {natural_query}")

        # Parse query
        parsed = self.parser.parse(natural_query)

        # Execute query
        results = self.executor.execute(parsed, game_id)

        # Log query
        if log_query:
            self.db.log_query(
                natural_query=natural_query,
                result_count=results["count"],
                execution_time_ms=results["execution_time_ms"],
            )

        # Add parsed info to results
        results["parsed"] = {
            "event_types": [et.value for et in parsed.event_types],
            "player_filter": parsed.player_filter,
            "time_filter": parsed.time_filter,
            "outcome_filter": parsed.outcome_filter.value if parsed.outcome_filter else None,
        }

        return results

    def get_suggestions(self, partial_query: str) -> List[str]:
        """
        Get query suggestions based on partial input.

        Args:
            partial_query: Partial query string

        Returns:
            List of suggested completions
        """
        suggestions = []
        partial_lower = partial_query.lower()

        # Suggest event types
        for keyword in QueryParser.EVENT_KEYWORDS.keys():
            if keyword.startswith(partial_lower) or partial_lower in keyword:
                suggestions.append(f"Show me all {keyword}")

        # Suggest player-specific queries
        if "goalkeeper" in partial_lower or "saves" in partial_lower:
            suggestions.extend([
                "Show me all saves by the goalkeeper",
                "Show goalkeeper distribution",
                "Show goalkeeper one on ones",
            ])

        # Suggest time-based queries
        if "half" in partial_lower or "minute" in partial_lower:
            suggestions.extend([
                "Events in the first half",
                "Goals in the second half",
                "Shots after 60 minutes",
            ])

        # Limit suggestions
        return suggestions[:10]

    def get_player_summary(self, game_id: int, player_id: int) -> Dict[str, Any]:
        """
        Get a summary of all events for a player.

        Args:
            game_id: Game ID
            player_id: Player ID

        Returns:
            Player event summary
        """
        with self.db.get_session() as session:
            player = session.query(Player).filter(Player.id == player_id).first()
            if not player:
                return {"error": "Player not found"}

            events = session.query(Event).filter(
                Event.game_id == game_id,
                Event.player_id == player_id
            ).all()

            # Group events by type
            event_counts = {}
            for event in events:
                event_type = event.event_type.value
                if event_type not in event_counts:
                    event_counts[event_type] = 0
                event_counts[event_type] += 1

            return {
                "player": {
                    "id": player.id,
                    "name": player.name,
                    "jersey_number": player.jersey_number,
                    "team": player.team,
                    "position": player.position.value if player.position else None,
                },
                "total_events": len(events),
                "event_counts": event_counts,
                "timestamps": [
                    {
                        "timestamp_sec": e.timestamp_sec,
                        "event_type": e.event_type.value,
                    }
                    for e in sorted(events, key=lambda x: x.timestamp_sec)
                ],
            }
