"""Allow only one primary account while retaining existing account credentials."""
from alembic import op
import sqlalchemy as sa

revision = '20261027_primary_account'
down_revision = '20261027_followup_handled'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('uq_users_primary_account', 'users', ['role'], unique=True,
                    postgresql_where=sa.text("role = 'admin'"), sqlite_where=sa.text("role = 'admin'"))


def downgrade():
    op.drop_index('uq_users_primary_account', table_name='users')
