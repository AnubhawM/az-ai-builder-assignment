# init_db.py
# Initializes the SQLite database and seeds it with demo personas.
# Run this once: python init_db.py

import os
import sys

# Ensure the backend directory is in the path
sys.path.insert(0, os.path.dirname(__file__))

from database.config import engine
from database import Base, SessionLocal
from database.models import User, Workflow, WorkflowStep, WorkflowEvent, WorkRequest, Volunteer


def create_tables():
    """Create all tables defined in models.py."""
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("✅ Tables created successfully.")


def seed_users():
    """Pre-seed the database with demo personas for the Capability Exchange."""
    db = SessionLocal()
    try:
        # Check if users already exist (idempotent seeding)
        existing_count = db.query(User).count()
        if existing_count > 0:
            print(f"ℹ️  Database already has {existing_count} user(s). Skipping seed.")
            return

        demo_users = [
            {
                "name": "Dr. Anubhaw",
                "email": "anubhaw@aixplore.demo",
                "role": "researcher",
                "slack_user_id": None,  # Set after Slack app is configured
            },
            {
                "name": "Jane",
                "email": "jane@aixplore.demo",
                "role": "compliance_expert",
                "slack_user_id": None,
            },
            {
                "name": "Alex",
                "email": "alex@aixplore.demo",
                "role": "design_reviewer",
                "slack_user_id": None,
            },
            {
                "name": "OpenClaw AI",
                "email": "agent@openclaw.ai",
                "role": "agent",
                "is_agent": True,
                "slack_user_id": None,
            },
        ]

        for user_data in demo_users:
            user = User(**user_data)
            db.add(user)

        db.commit()
        print(f"✅ Seeded {len(demo_users)} personas:")
        for u in demo_users:
            print(f"   → {u['name']} ({u['role']}) {'[AGENT]' if u.get('is_agent') else ''}")

    except Exception as e:
        db.rollback()
        print(f"❌ Error seeding users: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("=" * 50)
    print("AIXplore Capability Exchange — Database Setup")
    print("=" * 50)
    create_tables()
    seed_users()
    print("=" * 50)
    print("🚀 Database is ready!")
    print("=" * 50)
