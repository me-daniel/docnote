from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base

DATABASE_URL = "sqlite:///./medbridge.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}   # needed for SQLite
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Create all tables on startup."""
    Base.metadata.create_all(bind=engine)

def get_db():
    """Dependency — yields a DB session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
