"""routes.directions: turn-by-turn steps from OpenRouteService, for the app's directions list.

Null for routes saved before this; generating the trip's routes again fills it.

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("routes", sa.Column("directions", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("routes", "directions")
