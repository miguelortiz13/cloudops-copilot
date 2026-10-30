"""incidentes: alertas agrupadas y su diagnostico por el agente

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-30 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('incidents',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('key', sa.Unicode(length=450), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('cluster', sa.String(length=100), nullable=True),
    sa.Column('title', sa.Unicode(length=300), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('alerts', sa.JSON(), nullable=False),
    sa.Column('opened_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_alert_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('diagnosis_status', sa.String(length=16), nullable=False),
    sa.Column('diagnosis', sa.UnicodeText(), nullable=True),
    sa.Column('diagnosis_tools', sa.JSON(), nullable=False),
    sa.Column('diagnosed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('feedback', sa.String(length=16), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_incidents_key_status', 'incidents', ['key', 'status'], unique=False)
    op.create_index('ix_incidents_opened', 'incidents', ['opened_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_incidents_opened', table_name='incidents')
    op.drop_index('ix_incidents_key_status', table_name='incidents')
    op.drop_table('incidents')
