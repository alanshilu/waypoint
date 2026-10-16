"""Baseline: trips, routes and pois as create_tables.py made them.

A database that already has these tables must skip this revision:
    python -m alembic stamp 0001

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def point():
    return Geometry(geometry_type="POINT", srid=4326, spatial_index=False)


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "trips",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String, nullable=True),
        sa.Column("origin_name", sa.String, nullable=False),
        sa.Column("origin_point", point(), nullable=False),
        sa.Column("destination_name", sa.String, nullable=False),
        sa.Column("destination_point", point(), nullable=False),
        sa.Column("selected_route_id", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )
    op.create_table(
        "routes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("trip_id", sa.Integer, sa.ForeignKey("trips.id", name="routes_trip_id_fkey"), nullable=False),
        sa.Column("route_type", sa.String, nullable=False),
        sa.Column("distance_miles", sa.Float, nullable=False),
        sa.Column("duration_seconds", sa.Integer, nullable=False),
        sa.Column(
            "geometry",
            Geometry(geometry_type="LINESTRING", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("ascent_m", sa.Float, nullable=True),
        sa.Column("descent_m", sa.Float, nullable=True),
        sa.Column("scenic_score", sa.Float, nullable=True),
        sa.Column("is_selected", sa.Boolean, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )
    # trips and routes reference each other, so this key is added once both exist
    op.create_foreign_key("trips_selected_route_id_fkey", "trips", "routes", ["selected_route_id"], ["id"])
    op.create_table(
        "pois",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("category", sa.String, nullable=False),
        sa.Column("location", point(), nullable=False),
        sa.Column("source", sa.String, nullable=False),
        sa.Column("external_id", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )

    op.create_index("idx_trips_origin_point", "trips", ["origin_point"], postgresql_using="gist")
    op.create_index("idx_trips_destination_point", "trips", ["destination_point"], postgresql_using="gist")
    op.create_index("idx_routes_geometry", "routes", ["geometry"], postgresql_using="gist")
    op.create_index("idx_pois_location", "pois", ["location"], postgresql_using="gist")


def downgrade():
    op.drop_constraint("trips_selected_route_id_fkey", "trips", type_="foreignkey")
    op.drop_table("pois")
    op.drop_table("routes")
    op.drop_table("trips")
