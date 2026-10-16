"""Elevation profile, timezone-aware timestamps, unique POIs, one selected route per trip.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# trips and pois were written with timezone-aware datetimes into columns
# without a time zone, so PostgreSQL stored them in the session's local time.
# routes used datetime.utcnow(), so those values really are UTC.
LOCAL_TIME_COLUMNS = [("trips", "created_at"), ("trips", "updated_at"), ("pois", "created_at")]
UTC_COLUMNS = [("routes", "created_at")]


def upgrade():
    op.add_column("routes", sa.Column("elevation_profile", sa.JSON, nullable=True))

    for table, column in LOCAL_TIME_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE timestamptz "
            f"USING {column} AT TIME ZONE current_setting('TimeZone')"
        )
    for table, column in UTC_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE timestamptz "
            f"USING {column} AT TIME ZONE 'UTC'"
        )

    op.create_unique_constraint("uq_pois_source_external_id", "pois", ["source", "external_id"])

    # /routes/select never cleared the previous choice; trips.selected_route_id is the truth
    op.execute(
        "UPDATE routes r SET is_selected = COALESCE(r.id = t.selected_route_id, false) "
        "FROM trips t WHERE t.id = r.trip_id"
    )


def downgrade():
    op.drop_constraint("uq_pois_source_external_id", "pois", type_="unique")

    for table, column in LOCAL_TIME_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE timestamp "
            f"USING {column} AT TIME ZONE current_setting('TimeZone')"
        )
    for table, column in UTC_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE timestamp "
            f"USING {column} AT TIME ZONE 'UTC'"
        )

    op.drop_column("routes", "elevation_profile")
