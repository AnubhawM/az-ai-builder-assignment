# database/config.py
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
import os
from dotenv import load_dotenv

# Load environment variables from backend/.env
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
load_dotenv(dotenv_path=env_path)

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./database/aixplore-marketplace.db')

# Detect if we're using SQLite vs another database
is_sqlite = DATABASE_URL.startswith('sqlite')

if is_sqlite:
    # SQLite configuration:
    # - StaticPool: reuses a single connection (ideal for SQLite)
    # - check_same_thread=False: allows Flask threads to share the connection
    engine = create_engine(
        DATABASE_URL,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        echo=False
    )
else:
    # PostgreSQL / other database configuration with connection pooling
    from sqlalchemy.pool import QueuePool
    engine = create_engine(
        DATABASE_URL,
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_pre_ping=True,
        echo=False
    )