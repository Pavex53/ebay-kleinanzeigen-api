"""
Database configuration for Kleinanzeigen SaaS backend.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from backend.models import Base


class Database:
    """Database connection manager."""

    def __init__(self, database_url: str):
        self.engine = create_engine(
            database_url,
            pool_pre_ping=True,  # Auto-reconnect on connection loss
            echo=False  # Set to True for SQL debugging
        )
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine
        )

    def create_tables(self):
        """Create all tables in the database."""
        Base.metadata.create_all(bind=self.engine)

    def get_session(self) -> Session:
        """Get a database session."""
        session = self.SessionLocal()
        try:
            yield session
        finally:
            session.close()


# Global database instance (initialized in main.py)
db: Database | None = None


def get_db() -> Session:
    """Dependency for FastAPI to get DB session."""
    if db is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    return next(db.get_session())
