"""Keep source workbooks and source row positions for student job exports."""
from alembic import op
import sqlalchemy as sa

revision = '20261029_job_excel_export'
down_revision = '20261029_campus_import'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('import_batches', sa.Column('source_file', sa.LargeBinary(), nullable=True))
    op.add_column('import_batches', sa.Column('source_sheet', sa.String(31), nullable=True))
    with op.batch_alter_table('jobs') as batch:
        batch.add_column(sa.Column('source_batch_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('source_row_number', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_jobs_source_batch', 'import_batches', ['source_batch_id'], ['id'])


def downgrade():
    with op.batch_alter_table('jobs') as batch:
        batch.drop_constraint('fk_jobs_source_batch', type_='foreignkey')
        batch.drop_column('source_row_number')
        batch.drop_column('source_batch_id')
    op.drop_column('import_batches', 'source_sheet')
    op.drop_column('import_batches', 'source_file')
