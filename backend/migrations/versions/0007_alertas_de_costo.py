"""alertas de costo gestionables

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-09 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('cost_events',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('key', sa.String(length=300), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('provider', sa.String(length=16), nullable=False),
    sa.Column('account_uid', sa.String(length=200), nullable=True),
    sa.Column('day', sa.Date(), nullable=True),
    sa.Column('amount', sa.Float(), nullable=False),
    sa.Column('reference', sa.Float(), nullable=True),
    sa.Column('title', sa.Unicode(length=300), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('assignee', sa.Unicode(length=200), nullable=True),
    sa.Column('note', sa.UnicodeText(), nullable=True),
    sa.Column('explanation', sa.UnicodeText(), nullable=True),
    sa.Column('opened_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_by', sa.Unicode(length=320), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key', name='uq_cost_events_key')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('cost_events')
