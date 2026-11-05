"""gestion de incidentes: responsable, cierre, post-mortem, tormentas y linea de tiempo

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-05 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('incidents') as t:
        t.add_column(sa.Column('assignee', sa.Unicode(length=200), nullable=True))
        t.add_column(sa.Column('closed_reason', sa.String(length=32), nullable=True))
        t.add_column(sa.Column('postmortem', sa.UnicodeText(), nullable=True))
        t.add_column(sa.Column('parent_id', sa.Integer(), nullable=True))
        t.create_foreign_key('fk_incidents_parent', 'incidents', ['parent_id'], ['id'])
        t.create_index('ix_incidents_parent_id', ['parent_id'], unique=False)
    op.create_table('incident_events',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('incident_id', sa.Integer(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('actor', sa.Unicode(length=200), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('text', sa.UnicodeText(), nullable=False),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_incident_events_incident_id', 'incident_events', ['incident_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_incident_events_incident_id', table_name='incident_events')
    op.drop_table('incident_events')
    with op.batch_alter_table('incidents') as t:
        t.drop_index('ix_incidents_parent_id')
        t.drop_constraint('fk_incidents_parent', type_='foreignkey')
        t.drop_column('parent_id')
        t.drop_column('postmortem')
        t.drop_column('closed_reason')
        t.drop_column('assignee')
