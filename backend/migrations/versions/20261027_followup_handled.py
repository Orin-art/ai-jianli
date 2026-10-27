"""Persist follow-up completion and the associated job for historical cards."""
from alembic import op
import sqlalchemy as sa

revision = '20261027_followup_handled'
down_revision = '20261025_resume_ocr_cache'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('followups', sa.Column('handled_at', sa.DateTime(), nullable=True))
    op.add_column('followups', sa.Column('job_snapshot', sa.JSON(), nullable=True))
    followups = sa.table('followups', sa.column('recommendation_id', sa.Integer()), sa.column('job_snapshot', sa.JSON()))
    recommendations = sa.table('recommendations', sa.column('id', sa.Integer()), sa.column('snapshot', sa.JSON()))
    op.execute(followups.update().values(job_snapshot=sa.select(recommendations.c.snapshot).where(recommendations.c.id == followups.c.recommendation_id).scalar_subquery()))


def downgrade():
    op.drop_column('followups', 'job_snapshot')
    op.drop_column('followups', 'handled_at')
