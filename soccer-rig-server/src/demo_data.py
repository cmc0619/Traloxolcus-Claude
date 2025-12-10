"""
Demo Data Generator

Creates sample data for testing features:
- Organizations, teams, players
- Parents with linked children
- Games with events and clips
- Stats (game and season)

All demo data is prefixed with "DEMO_" for easy identification and deletion.
"""

import random
from datetime import datetime, date, timedelta
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)

# Demo data marker prefix
DEMO_PREFIX = "DEMO_"

# Sample names
FIRST_NAMES = [
    "Marcus", "Sophia", "Lucas", "Emma", "Oliver", "Ava", "William", "Mia",
    "James", "Isabella", "Alexander", "Charlotte", "Benjamin", "Amelia",
    "Ethan", "Harper", "Mason", "Evelyn", "Henry", "Abigail"
]

LAST_NAMES = [
    "Johnson", "Smith", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Anderson", "Taylor", "Thomas",
    "Hernandez", "Moore", "Martin", "Jackson", "Thompson", "White", "Lopez"
]

TEAM_COLORS = [
    ("#1E3A8A", "#60A5FA"),  # Blue
    ("#991B1B", "#F87171"),  # Red
    ("#166534", "#4ADE80"),  # Green
    ("#7C2D12", "#FB923C"),  # Orange
    ("#581C87", "#C084FC"),  # Purple
]


def generate_demo_data(db) -> dict:
    """
    Generate demo data for testing.

    Returns dict with created record counts.
    """
    from .models import (
        User, Player, Organization, Team, Game, GameEvent,
        Clip, PlayerGameStats, Recording, Notification,
        UserRole, PlayerPosition, EventType, NotificationFrequency,
        parent_player, team_player
    )

    logger.info("Generating demo data...")
    counts = {
        'organizations': 0,
        'teams': 0,
        'players': 0,
        'parents': 0,
        'games': 0,
        'events': 0,
        'clips': 0,
        'stats': 0
    }

    # Create demo organization
    org = Organization(
        name=f"{DEMO_PREFIX}Riverside Soccer Club",
        slug=f"{DEMO_PREFIX.lower()}riverside-sc",
        primary_color="#1E3A8A",
        secondary_color="#60A5FA",
        email="demo@riverside-soccer.example.com",
        website="https://riverside-soccer.example.com"
    )
    db.add(org)
    db.flush()
    counts['organizations'] = 1

    # Create 2 demo teams (different birth years)
    teams = []
    for i, (birth_year, team_name) in enumerate([
        (2012, "Blue Lightning"),
        (2014, "Green Strikers")
    ]):
        primary, secondary = TEAM_COLORS[i]
        team = Team(
            organization_id=org.id,
            name=f"{DEMO_PREFIX}{team_name}",
            team_code=f"DEMO{birth_year}",
            birth_year_start=birth_year,
            birth_year_end=birth_year,
            season="Fall 2024",
            year=2024,
            primary_color=primary,
            secondary_color=secondary,
            is_active=True
        )
        db.add(team)
        teams.append(team)
    db.flush()
    counts['teams'] = len(teams)

    # Create players and parents for each team
    all_players = []
    all_parents = []

    for team_idx, team in enumerate(teams):
        # 11 players per team
        positions = [
            (PlayerPosition.GOALKEEPER, 1),
            (PlayerPosition.DEFENDER, 2),
            (PlayerPosition.DEFENDER, 3),
            (PlayerPosition.DEFENDER, 4),
            (PlayerPosition.DEFENDER, 5),
            (PlayerPosition.MIDFIELDER, 6),
            (PlayerPosition.MIDFIELDER, 7),
            (PlayerPosition.MIDFIELDER, 8),
            (PlayerPosition.FORWARD, 9),
            (PlayerPosition.FORWARD, 10),
            (PlayerPosition.FORWARD, 11),
        ]

        for pos, jersey in positions:
            first_name = random.choice(FIRST_NAMES)
            last_name = random.choice(LAST_NAMES)

            player = Player(
                first_name=f"{DEMO_PREFIX}{first_name}",
                last_name=last_name,
                birth_year=team.birth_year_start,
                default_position=pos
            )
            db.add(player)
            all_players.append((player, team, jersey))

            # Create parent for this player
            parent = User(
                email=f"demo.parent.{len(all_parents)}@example.com",
                first_name=f"{DEMO_PREFIX}Parent",
                last_name=last_name,
                role=UserRole.PARENT,
                notify_frequency=NotificationFrequency.INSTANT,
                notify_goals=True,
                notify_saves=True,
                notify_highlights=True,
                notify_game_ready=True
            )
            parent.set_password("demo123")
            db.add(parent)
            all_parents.append((parent, player))

    db.flush()
    counts['players'] = len(all_players)
    counts['parents'] = len(all_parents)

    # Link players to teams with jersey numbers
    for player, team, jersey in all_players:
        db.execute(
            team_player.insert().values(
                team_id=team.id,
                player_id=player.id,
                jersey_number=str(jersey),
                position=player.default_position.value,
                is_active=True
            )
        )

    # Link parents to players
    for parent, player in all_parents:
        db.execute(
            parent_player.insert().values(
                parent_id=parent.id,
                player_id=player.id,
                relationship='parent'
            )
        )

    # Create games for each team
    all_games = []
    opponents = ["FC United", "City Rovers", "Athletic Club", "Rangers SC"]

    for team in teams:
        # 3 games per team
        team_players = [p for p, t, _ in all_players if t.id == team.id]

        for game_num in range(3):
            game_date = datetime.now() - timedelta(days=(3 - game_num) * 7)
            home_score = random.randint(0, 4)
            away_score = random.randint(0, 3)

            game = Game(
                team_id=team.id,
                opponent=f"{DEMO_PREFIX}{opponents[game_num % len(opponents)]}",
                location="Demo Field #1",
                game_date=game_date,
                game_type="league",
                home_score=home_score,
                away_score=away_score,
                is_home=(game_num % 2 == 0),
                session_id=f"DEMO_SESSION_{team.id}_{game_num}",
                duration_seconds=5400,  # 90 minutes
                is_processed=True,
                processed_at=game_date + timedelta(hours=2)
            )
            db.add(game)
            all_games.append((game, team_players))

    db.flush()
    counts['games'] = len(all_games)

    # Create events and clips for each game
    event_id = 0
    for game, team_players in all_games:
        # Generate 15-30 events per game
        num_events = random.randint(15, 30)
        game_events = []

        for _ in range(num_events):
            player = random.choice(team_players)
            event_type = random.choice([
                EventType.GOAL, EventType.SHOT, EventType.SHOT_ON_TARGET,
                EventType.PASS, EventType.TACKLE, EventType.INTERCEPTION,
                EventType.DRIBBLE
            ])

            # Goalkeeper-specific events
            if player.default_position == PlayerPosition.GOALKEEPER:
                event_type = random.choice([
                    EventType.SAVE, EventType.SAVE_DIVING, EventType.CATCH,
                    EventType.PUNCH, EventType.GOAL_KICK, EventType.DISTRIBUTION
                ])

            timestamp = random.uniform(0, 5400)

            event = GameEvent(
                game_id=game.id,
                player_id=player.id,
                event_type=event_type,
                timestamp_seconds=timestamp,
                confidence=random.uniform(0.75, 0.99),
                field_position_x=random.uniform(0.1, 0.9),
                field_position_y=random.uniform(0.1, 0.9),
                description=f"{DEMO_PREFIX}{event_type.value} by {player.first_name}"
            )
            db.add(event)
            game_events.append(event)

        db.flush()
        counts['events'] += len(game_events)

        # Create clips for goals and saves
        for event in game_events:
            if event.event_type in [EventType.GOAL, EventType.SAVE, EventType.SAVE_DIVING]:
                clip = Clip(
                    game_id=game.id,
                    event_id=event.id,
                    title=f"{DEMO_PREFIX}{event.event_type.value.title()} - {event.display_time}",
                    description=event.description,
                    file_path=f"/demo/clips/{game.id}_{event.id}.mp4",
                    duration_seconds=15,
                    start_time=max(0, event.timestamp_seconds - 5),
                    end_time=event.timestamp_seconds + 10,
                    is_highlight=True,
                    is_public=True
                )
                db.add(clip)
                counts['clips'] += 1

        # Create player game stats
        for player in team_players:
            player_events = [e for e in game_events if e.player_id == player.id]

            stats = PlayerGameStats(
                player_id=player.id,
                game_id=game.id,
                goals=sum(1 for e in player_events if e.event_type == EventType.GOAL),
                assists=sum(1 for e in player_events if e.event_type == EventType.ASSIST),
                shots=sum(1 for e in player_events if e.event_type in [EventType.SHOT, EventType.SHOT_ON_TARGET]),
                shots_on_target=sum(1 for e in player_events if e.event_type == EventType.SHOT_ON_TARGET),
                passes=sum(1 for e in player_events if e.event_type == EventType.PASS),
                tackles=sum(1 for e in player_events if e.event_type == EventType.TACKLE),
                interceptions=sum(1 for e in player_events if e.event_type == EventType.INTERCEPTION),
                saves=sum(1 for e in player_events if e.event_type in [EventType.SAVE, EventType.SAVE_DIVING]),
                saves_diving=sum(1 for e in player_events if e.event_type == EventType.SAVE_DIVING),
                minutes_played=random.randint(45, 90)
            )
            db.add(stats)
            counts['stats'] += 1

    db.commit()

    logger.info(f"Demo data created: {counts}")
    return counts


def delete_demo_data(db) -> dict:
    """
    Delete all demo data.

    Returns dict with deleted record counts.
    """
    from .models import (
        User, Player, Organization, Team, Game, GameEvent,
        Clip, PlayerGameStats, PlayerSeasonStats, Recording, Notification,
        parent_player, team_player, team_coach
    )
    from sqlalchemy import delete

    logger.info("Deleting demo data...")
    counts = {
        'organizations': 0,
        'teams': 0,
        'players': 0,
        'users': 0,
        'games': 0,
        'events': 0,
        'clips': 0,
        'stats': 0
    }

    # Find demo organizations
    demo_orgs = db.query(Organization).filter(
        Organization.name.like(f"{DEMO_PREFIX}%")
    ).all()
    org_ids = [o.id for o in demo_orgs]

    # Find demo teams
    demo_teams = db.query(Team).filter(
        Team.name.like(f"{DEMO_PREFIX}%")
    ).all()
    team_ids = [t.id for t in demo_teams]

    # Find demo games
    demo_games = db.query(Game).filter(
        Game.session_id.like("DEMO_%")
    ).all()
    game_ids = [g.id for g in demo_games]

    # Find demo players
    demo_players = db.query(Player).filter(
        Player.first_name.like(f"{DEMO_PREFIX}%")
    ).all()
    player_ids = [p.id for p in demo_players]

    # Find demo users (parents)
    demo_users = db.query(User).filter(
        User.email.like("demo.parent.%@example.com")
    ).all()
    user_ids = [u.id for u in demo_users]

    # Delete in dependency order

    # 1. Delete notifications
    if user_ids:
        db.query(Notification).filter(
            Notification.user_id.in_(user_ids)
        ).delete(synchronize_session=False)

    # 2. Delete clips
    if game_ids:
        counts['clips'] = db.query(Clip).filter(
            Clip.game_id.in_(game_ids)
        ).delete(synchronize_session=False)

    # 3. Delete game events
    if game_ids:
        counts['events'] = db.query(GameEvent).filter(
            GameEvent.game_id.in_(game_ids)
        ).delete(synchronize_session=False)

    # 4. Delete player stats
    if game_ids:
        counts['stats'] = db.query(PlayerGameStats).filter(
            PlayerGameStats.game_id.in_(game_ids)
        ).delete(synchronize_session=False)

    # 5. Delete season stats
    if team_ids:
        db.query(PlayerSeasonStats).filter(
            PlayerSeasonStats.team_id.in_(team_ids)
        ).delete(synchronize_session=False)

    # 6. Delete games
    counts['games'] = len(game_ids)
    for game in demo_games:
        db.delete(game)

    # 7. Delete association table entries
    if player_ids:
        db.execute(delete(parent_player).where(
            parent_player.c.player_id.in_(player_ids)
        ))
        db.execute(delete(team_player).where(
            team_player.c.player_id.in_(player_ids)
        ))

    if team_ids:
        db.execute(delete(team_coach).where(
            team_coach.c.team_id.in_(team_ids)
        ))

    # 8. Delete players
    counts['players'] = len(player_ids)
    for player in demo_players:
        db.delete(player)

    # 9. Delete users
    counts['users'] = len(user_ids)
    for user in demo_users:
        db.delete(user)

    # 10. Delete teams
    counts['teams'] = len(team_ids)
    for team in demo_teams:
        db.delete(team)

    # 11. Delete organizations
    counts['organizations'] = len(org_ids)
    for org in demo_orgs:
        db.delete(org)

    db.commit()

    logger.info(f"Demo data deleted: {counts}")
    return counts


def has_demo_data(db) -> bool:
    """Check if demo data exists."""
    from .models import Organization
    return db.query(Organization).filter(
        Organization.name.like(f"{DEMO_PREFIX}%")
    ).first() is not None


# =============================================================================
# Admin Routes for Demo Data
# =============================================================================

def register_demo_routes(app, db):
    """Register demo data admin routes."""
    from flask import jsonify, request
    from functools import wraps
    from .admin import admin_required

    @app.route('/api/admin/demo/status')
    @admin_required
    def demo_status():
        """Check if demo data exists."""
        return jsonify({
            'has_demo_data': has_demo_data(db),
            'prefix': DEMO_PREFIX
        })

    @app.route('/api/admin/demo/generate', methods=['POST'])
    @admin_required
    def generate_demo():
        """Generate demo data."""
        if has_demo_data(db):
            return jsonify({
                'error': 'Demo data already exists. Delete it first.'
            }), 400

        try:
            counts = generate_demo_data(db)
            return jsonify({
                'message': 'Demo data generated successfully',
                'counts': counts
            })
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to generate demo data: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/admin/demo/delete', methods=['DELETE'])
    @admin_required
    def delete_demo():
        """Delete all demo data."""
        if not has_demo_data(db):
            return jsonify({
                'error': 'No demo data to delete.'
            }), 400

        try:
            counts = delete_demo_data(db)
            return jsonify({
                'message': 'Demo data deleted successfully',
                'counts': counts
            })
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to delete demo data: {e}")
            return jsonify({'error': str(e)}), 500


# Demo login credentials displayed on admin page
DEMO_CREDENTIALS = """
Demo Parent Logins (all use password: demo123):
- demo.parent.0@example.com (Blue Lightning team)
- demo.parent.11@example.com (Green Strikers team)

Demo Features:
- 2 teams with 11 players each
- 3 games per team with events and clips
- Stats for all players
- Heat maps with position data
"""
