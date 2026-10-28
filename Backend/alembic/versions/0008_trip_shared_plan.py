"""trips.shared_plan: the latest plan the agent made for the trip, for its share link.

{"planned_stops": [...], "places": [...], "saved_at": ISO time}: the overnight stops it recommended and the
places it found, as the app showed them. Until now these lived only in the agent's reply. Null until a turn
plans stops or finds places for the trip.

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("trips", sa.Column("shared_plan", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("trips", "shared_plan")
