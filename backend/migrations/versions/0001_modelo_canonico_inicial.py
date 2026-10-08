"""modelo canonico inicial

Revision ID: 0001
Revises: 
Create Date: 2026-10-08 11:32:15.738842

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('accounts',
    sa.Column('uid', sa.String(length=200), nullable=False),
    sa.Column('provider', sa.String(length=16), nullable=False),
    sa.Column('native_id', sa.String(length=100), nullable=False),
    sa.Column('name', sa.Unicode(length=200), nullable=False),
    sa.Column('parent', sa.String(length=200), nullable=True),
    sa.Column('first_seen', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('uid')
    )
    op.create_table('collector_runs',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('collector', sa.String(length=32), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('items', sa.Integer(), nullable=False),
    sa.Column('detail', sa.JSON(), nullable=False),
    sa.Column('error', sa.UnicodeText(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_collector_runs_collector_started', 'collector_runs', ['collector', 'started_at'], unique=False)
    op.create_table('cost_daily',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('charge_date', sa.Date(), nullable=False),
    sa.Column('account_uid', sa.String(length=200), nullable=False),
    sa.Column('resource_uid', sa.String(length=450), nullable=False),
    sa.Column('service_name', sa.Unicode(length=200), nullable=False),
    sa.Column('billed_cost', sa.Numeric(precision=18, scale=6), nullable=False),
    sa.Column('effective_cost', sa.Numeric(precision=18, scale=6), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('charge_date', 'account_uid', 'resource_uid', 'service_name', 'source', name='uq_cost_daily')
    )
    op.create_index('ix_cost_daily_account_date', 'cost_daily', ['account_uid', 'charge_date'], unique=False)
    op.create_table('kpi_daily',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('scope', sa.String(length=200), nullable=False),
    sa.Column('metric', sa.String(length=64), nullable=False),
    sa.Column('value', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('day', 'scope', 'metric', name='uq_kpi_daily')
    )
    op.create_table('rules',
    sa.Column('id', sa.String(length=100), nullable=False),
    sa.Column('capability', sa.String(length=32), nullable=False),
    sa.Column('title', sa.Unicode(length=300), nullable=False),
    sa.Column('severity_default', sa.String(length=16), nullable=False),
    sa.Column('frameworks', sa.JSON(), nullable=False),
    sa.Column('remediation', sa.UnicodeText(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('findings',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('rule_id', sa.String(length=100), nullable=False),
    sa.Column('resource_uid', sa.String(length=450), nullable=False),
    sa.Column('account_uid', sa.String(length=200), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('owner', sa.Unicode(length=320), nullable=True),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('accepted_until', sa.Date(), nullable=True),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.Column('first_seen', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen', sa.DateTime(timezone=True), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['rule_id'], ['rules.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('rule_id', 'resource_uid', name='uq_finding_rule_resource')
    )
    op.create_index(op.f('ix_findings_account_uid'), 'findings', ['account_uid'], unique=False)
    op.create_index('ix_findings_status', 'findings', ['status'], unique=False)
    op.create_table('resources',
    sa.Column('uid', sa.String(length=450), nullable=False),
    sa.Column('provider', sa.String(length=16), nullable=False),
    sa.Column('account_uid', sa.String(length=200), nullable=False),
    sa.Column('name', sa.Unicode(length=260), nullable=False),
    sa.Column('canonical_type', sa.String(length=64), nullable=True),
    sa.Column('native_type', sa.String(length=200), nullable=False),
    sa.Column('region', sa.String(length=64), nullable=True),
    sa.Column('group_name', sa.Unicode(length=200), nullable=True),
    sa.Column('tags', sa.JSON(), nullable=False),
    sa.Column('in_iac_state', sa.Boolean(), nullable=True),
    sa.Column('created_by', sa.Unicode(length=320), nullable=True),
    sa.Column('first_seen', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen', sa.DateTime(timezone=True), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['account_uid'], ['accounts.uid'], ),
    sa.PrimaryKeyConstraint('uid')
    )
    op.create_index(op.f('ix_resources_account_uid'), 'resources', ['account_uid'], unique=False)
    op.create_index(op.f('ix_resources_canonical_type'), 'resources', ['canonical_type'], unique=False)
    op.create_table('finding_events',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('finding_id', sa.Integer(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('from_status', sa.String(length=16), nullable=True),
    sa.Column('to_status', sa.String(length=16), nullable=True),
    sa.Column('actor', sa.Unicode(length=320), nullable=False),
    sa.Column('note', sa.UnicodeText(), nullable=True),
    sa.ForeignKeyConstraint(['finding_id'], ['findings.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_finding_events_finding_id'), 'finding_events', ['finding_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_finding_events_finding_id'), table_name='finding_events')
    op.drop_table('finding_events')
    op.drop_index(op.f('ix_resources_canonical_type'), table_name='resources')
    op.drop_index(op.f('ix_resources_account_uid'), table_name='resources')
    op.drop_table('resources')
    op.drop_index('ix_findings_status', table_name='findings')
    op.drop_index(op.f('ix_findings_account_uid'), table_name='findings')
    op.drop_table('findings')
    op.drop_table('rules')
    op.drop_table('kpi_daily')
    op.drop_index('ix_cost_daily_account_date', table_name='cost_daily')
    op.drop_table('cost_daily')
    op.drop_index('ix_collector_runs_collector_started', table_name='collector_runs')
    op.drop_table('collector_runs')
    op.drop_table('accounts')
