"""Cache private resume extraction results for immutable resume versions."""
from alembic import op
import sqlalchemy as sa

revision = '20261025_resume_ocr_cache'
down_revision = '20261025_student_school'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('resumes', sa.Column('extraction_cache', sa.JSON(), nullable=True))
    op.add_column('resumes', sa.Column('extraction_version', sa.String(64), nullable=False, server_default=''))

def downgrade():
    op.drop_column('resumes', 'extraction_version')
    op.drop_column('resumes', 'extraction_cache')
