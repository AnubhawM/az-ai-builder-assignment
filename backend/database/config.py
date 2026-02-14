# database/config.py
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool, QueuePool
import os
from dotenv import load_dotenv

# Load environment variables from backend/.env
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
load_dotenv(dotenv_path=env_path)

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./database/aixplore-marketplace.db')

# Detect if we're using SQLite vs another database
is_sqlite = DATABASE_URL.startswith('sqlite')
is_in_memory_sqlite = DATABASE_URL in ("sqlite://", "sqlite:///:memory:") or DATABASE_URL.endswith(":memory:")

if is_sqlite:
    if is_in_memory_sqlite:
        # In-memory SQLite must use one shared connection.
        engine = create_engine(
            DATABASE_URL,
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
            echo=False
        )
    else:
        # File-backed SQLite with workflow/background threads:
        # use a real connection pool to avoid cross-thread cursor/result corruption.
        sqlite_pool_size = int(os.getenv("SQLITE_POOL_SIZE", "10"))
        sqlite_max_overflow = int(os.getenv("SQLITE_MAX_OVERFLOW", "20"))
        engine = create_engine(
            DATABASE_URL,
            poolclass=QueuePool,
            pool_size=sqlite_pool_size,
            max_overflow=sqlite_max_overflow,
            pool_timeout=30,
            pool_pre_ping=True,
            connect_args={
                "check_same_thread": False,
                "timeout": 30,
            },
            echo=False
        )

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()
else:
    # PostgreSQL / other database configuration with connection pooling
    engine = create_engine(
        DATABASE_URL,
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_pre_ping=True,
        echo=False
    )
