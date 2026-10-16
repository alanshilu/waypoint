"""Recompute stored scenic scores with the terrain-only formula.

The old score mixed terrain with pace (0.5 x seconds per mile), so slow roads
dominated it. The new score is terrain only, 0-100; see
app/services/scoring_service.py for the formula and the reference constant.
No schema change: routes.scenic_score keeps its name and type.

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# Must match scoring_service.HALF_SCORE_DENSITY_M_PER_MILE at the time of this migration
HALF_SCORE_DENSITY_M_PER_MILE = 40.0

DISTANCE = "(CASE WHEN distance_miles > 0 THEN distance_miles ELSE 1.0 END)"
DENSITY = f"((COALESCE(ascent_m, 0) + COALESCE(descent_m, 0)) / {DISTANCE})"


def upgrade():
    op.execute(
        f"UPDATE routes SET scenic_score = "
        f"ROUND((100 * {DENSITY} / ({DENSITY} + {HALF_SCORE_DENSITY_M_PER_MILE}))::numeric, 1)"
    )


def downgrade():
    # the previous formula: elevation per mile + 0.5 x seconds per mile
    op.execute(
        f"UPDATE routes SET scenic_score = "
        f"ROUND(({DENSITY} + (duration_seconds / {DISTANCE}) * 0.5)::numeric, 1)"
    )
