"""oportunidades de ahorro aplicadas

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-09 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('saving_actions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('resource_uid', sa.String(length=450), nullable=False),
    sa.Column('name', sa.Unicode(length=260), nullable=False),
    sa.Column('category', sa.Unicode(length=100), nullable=False),
    sa.Column('expected_monthly', sa.Float(), nullable=False),
    sa.Column('note', sa.UnicodeText(), nullable=True),
    sa.Column('applied_by', sa.Unicode(length=320), nullable=False),
    sa.Column('applied_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_saving_actions_resource_uid', 'saving_actions', ['resource_uid'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_saving_actions_resource_uid', table_name='saving_actions')
    op.drop_table('saving_actions')
