"""acciones de seguimiento de incidentes

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('incident_actions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('incident_id', sa.Integer(), nullable=False),
    sa.Column('text', sa.Unicode(length=500), nullable=False),
    sa.Column('owner', sa.Unicode(length=200), nullable=True),
    sa.Column('created_by', sa.Unicode(length=320), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('done_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_incident_actions_incident_id', 'incident_actions', ['incident_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_incident_actions_incident_id', table_name='incident_actions')
    op.drop_table('incident_actions')
