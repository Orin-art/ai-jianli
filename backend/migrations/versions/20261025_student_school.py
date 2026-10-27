"""Add school to student profiles without changing existing data."""
from alembic import op
import sqlalchemy as sa

revision = '20261025_student_school'
down_revision = '5bbff2162a8e'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('students', sa.Column('school', sa.String(200), nullable=False, server_default=''))

def downgrade():
    op.drop_column('students', 'school')
