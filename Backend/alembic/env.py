from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import settings
from app.core.db import Base
from app.models import trip, route, poi, places_cache  # noqa: F401

# Direct connection (DATABASE_URL_UNPOOLED on Neon), not the app's pooled one
engine = create_engine(settings.migration_database_url, poolclass=pool.NullPool)

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    # PostGIS owns spatial_ref_sys; keep autogenerate from trying to drop it
    return not (type_ == "table" and name == "spatial_ref_sys")


def run_migrations_offline():
    context.configure(
        url=engine.url.render_as_string(hide_password=False),
        target_metadata=target_metadata,
        include_object=include_object,
        compare_server_default=True,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            # off by default in Alembic; without it a missing DEFAULT never shows as a diff
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
