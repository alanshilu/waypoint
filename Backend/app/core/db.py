from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings

# connect_timeout: an unreachable database fails in seconds instead of the OS's TCP timeout (minutes),
# with room for a Neon compute waking from scale-to-zero
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args={"connect_timeout": 10})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()  # your models (trip.py, route.py, poi.py) will import this


def get_db():
    """FastAPI dependency -- use as: db: Session = Depends(get_db)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
