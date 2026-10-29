"""Preserve campus recruitment fields and accommodate source text lengths."""
from alembic import op
import sqlalchemy as sa

revision = '20261029_campus_import'
down_revision = '20261027_primary_account'
branch_labels = None
depends_on = None


def upgrade():
    # Long combined job titles can exceed PostgreSQL's B-tree entry size.
    op.drop_index('ix_jobs_title', table_name='jobs')
    with op.batch_alter_table('jobs') as batch:
        batch.add_column(sa.Column('recruitment_details', sa.JSON(), nullable=False, server_default='{}'))
        batch.alter_column('title', existing_type=sa.String(160), type_=sa.String(2000))
        batch.alter_column('city', existing_type=sa.String(80), type_=sa.String(1000))
        batch.alter_column('major', existing_type=sa.String(200), type_=sa.String(1000))


def downgrade():
    # Keep wider text columns so rollback does not truncate imported source values.
    with op.batch_alter_table('jobs') as batch:
        batch.drop_column('recruitment_details')
