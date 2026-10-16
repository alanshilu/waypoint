from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()  # your models (trip.py, route.py, poi.py) will import this


def get_db():
    """FastAPI dependency -- use as: db: Session = Depends(get_db)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()# Async SQLAlchemy engine and sessionmaker configuration placeholder (no coding allowed)
