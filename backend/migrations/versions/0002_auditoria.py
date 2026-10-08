"""auditoria

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-08 12:48:43.830842

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('audit_log',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('actor', sa.Unicode(length=320), nullable=False),
    sa.Column('actor_oid', sa.String(length=64), nullable=True),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('target', sa.Unicode(length=450), nullable=True),
    sa.Column('outcome', sa.String(length=16), nullable=False),
    sa.Column('detail', sa.JSON(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_log_at', 'audit_log', ['at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_audit_log_at', table_name='audit_log')
    op.drop_table('audit_log')
