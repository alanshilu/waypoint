import sys
from pathlib import Path

backend_root = Path(__file__).resolve().parent.parent
if str(backend_root) not in sys.path:
	sys.path.insert(0, str(backend_root))

from app.core.db import Base, engine
from app.models import trip, route, poi  # noqa: F401

print("Creating tables...")
Base.metadata.create_all(bind=engine)
print("Done. Tables created: trips, routes, pois")
# Schema changes are tracked by Alembic. On a new database, either run
# "python -m alembic upgrade head" instead of this script, or run
# "python -m alembic stamp head" after it.