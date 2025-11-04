from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings

# Create database engine
settings = get_settings()
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,  # validate connections in case the Pods proxy closes idle connections
    pool_recycle=1800,
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# Dependency for getting DB sessions
def get_db(): # type: ignore[no-untyped-def]
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
