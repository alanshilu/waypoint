"""trips.public_id: a random UUID for the trip's share link (/t/<public_id>), unique.

Integer trip ids can be counted through; a share link names the trip by this instead. Existing rows each get
their own UUID from the column default (gen_random_uuid() is built into PostgreSQL 13+).

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    # A volatile default is evaluated per row, so this fills every existing trip with a different UUID
    op.add_column("trips", sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=True,
                                     server_default=sa.text("gen_random_uuid()")))
    op.execute("UPDATE trips SET public_id = gen_random_uuid() WHERE public_id IS NULL")
    op.alter_column("trips", "public_id", nullable=False)
    op.create_index("uq_trips_public_id", "trips", ["public_id"], unique=True)


def downgrade():
    op.drop_index("uq_trips_public_id", table_name="trips")
    op.drop_column("trips", "public_id")
