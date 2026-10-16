from pathlib import Path
import sys

from sqlalchemy import text

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from .core.db import engine
else:
    from .core.db import engine

with engine.connect() as conn:
    result = conn.execute(text("SELECT 1"))
    print("Connected! SELECT 1 returned:", result.scalar())

    # Bonus check: confirm PostGIS is actually enabled
    postgis_version = conn.execute(text("SELECT PostGIS_Version();")).scalar()
    print("PostGIS version:", postgis_version)