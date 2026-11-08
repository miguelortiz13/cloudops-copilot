"""excepciones de control con vencimiento

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-08 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('control_exceptions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('framework', sa.String(length=64), nullable=False),
    sa.Column('control', sa.String(length=64), nullable=False),
    sa.Column('justification', sa.UnicodeText(), nullable=False),
    sa.Column('created_by', sa.Unicode(length=320), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('until', sa.Date(), nullable=False),
    sa.Column('revoked_by', sa.Unicode(length=320), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('control_exceptions')
