"""Integrity: timestamp defaults and NOT NULL, route CHECKs, FK delete rules, a lookup index.

- created_at / updated_at are backfilled, get DEFAULT now() and become NOT NULL.
- routes gets CHECKs on route_type, distance_miles and duration_seconds.
- Deleting a trip deletes its routes (ON DELETE CASCADE); deleting the
  selected route clears trips.selected_route_id (ON DELETE SET NULL).
- idx_routes_trip_type_created serves "newest route of each type for a trip"
  (GET /trips/{id} and route reuse in /routes/generate).

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE trips  SET created_at = COALESCE(created_at, now()), updated_at = COALESCE(updated_at, created_at, now())")
    op.execute("UPDATE routes SET created_at = COALESCE(created_at, now())")
    op.execute("UPDATE pois   SET created_at = COALESCE(created_at, now())")

    op.execute(
        "ALTER TABLE trips  ALTER COLUMN created_at SET DEFAULT now(), ALTER COLUMN created_at SET NOT NULL, "
        "ALTER COLUMN updated_at SET DEFAULT now(), ALTER COLUMN updated_at SET NOT NULL"
    )
    op.execute("ALTER TABLE routes ALTER COLUMN created_at SET DEFAULT now(), ALTER COLUMN created_at SET NOT NULL")
    op.execute("ALTER TABLE pois   ALTER COLUMN created_at SET DEFAULT now(), ALTER COLUMN created_at SET NOT NULL")

    op.execute(
        "ALTER TABLE routes "
        "ADD CONSTRAINT ck_routes_type CHECK (route_type IN ('fastest','backroads')), "
        "ADD CONSTRAINT ck_routes_distance CHECK (distance_miles > 0), "
        "ADD CONSTRAINT ck_routes_duration CHECK (duration_seconds > 0)"
    )

    op.execute(
        "ALTER TABLE routes DROP CONSTRAINT routes_trip_id_fkey, "
        "ADD CONSTRAINT routes_trip_id_fkey FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE"
    )
    op.execute(
        "ALTER TABLE trips DROP CONSTRAINT trips_selected_route_id_fkey, "
        "ADD CONSTRAINT trips_selected_route_id_fkey FOREIGN KEY (selected_route_id) REFERENCES routes(id) "
        "ON DELETE SET NULL"
    )

    op.execute("CREATE INDEX idx_routes_trip_type_created ON routes (trip_id, route_type, created_at DESC)")


def downgrade():
    # Reverses every schema change. The timestamp backfill is not undone:
    # the rows that were NULL before cannot be told apart afterwards.
    op.execute("DROP INDEX idx_routes_trip_type_created")

    op.execute(
        "ALTER TABLE trips DROP CONSTRAINT trips_selected_route_id_fkey, "
        "ADD CONSTRAINT trips_selected_route_id_fkey FOREIGN KEY (selected_route_id) REFERENCES routes(id)"
    )
    op.execute(
        "ALTER TABLE routes DROP CONSTRAINT routes_trip_id_fkey, "
        "ADD CONSTRAINT routes_trip_id_fkey FOREIGN KEY (trip_id) REFERENCES trips(id)"
    )

    op.execute(
        "ALTER TABLE routes DROP CONSTRAINT ck_routes_duration, DROP CONSTRAINT ck_routes_distance, "
        "DROP CONSTRAINT ck_routes_type"
    )

    op.execute("ALTER TABLE pois   ALTER COLUMN created_at DROP NOT NULL, ALTER COLUMN created_at DROP DEFAULT")
    op.execute("ALTER TABLE routes ALTER COLUMN created_at DROP NOT NULL, ALTER COLUMN created_at DROP DEFAULT")
    op.execute(
        "ALTER TABLE trips  ALTER COLUMN updated_at DROP NOT NULL, ALTER COLUMN updated_at DROP DEFAULT, "
        "ALTER COLUMN created_at DROP NOT NULL, ALTER COLUMN created_at DROP DEFAULT"
    )
