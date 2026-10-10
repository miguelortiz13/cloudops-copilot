"""cumplimiento: detalle de reglas y clasificacion de activos

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-10 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('rules') as batch:
        batch.add_column(sa.Column('description', sa.UnicodeText(), nullable=True))
        batch.add_column(sa.Column('detection', sa.UnicodeText(), nullable=True))
        batch.add_column(sa.Column('reference_urls', sa.JSON(), nullable=True))

    op.create_table('asset_classifications',
    sa.Column('resource_uid', sa.String(length=450), nullable=False),
    sa.Column('classification', sa.Unicode(length=32), nullable=False),
    sa.Column('confidentiality', sa.Integer(), nullable=False),
    sa.Column('integrity', sa.Integer(), nullable=False),
    sa.Column('availability', sa.Integer(), nullable=False),
    sa.Column('risk_required', sa.Boolean(), nullable=False),
    sa.Column('custodian', sa.Unicode(length=320), nullable=True),
    sa.Column('method', sa.String(length=16), nullable=False),
    sa.Column('reason', sa.UnicodeText(), nullable=True),
    sa.Column('updated_by', sa.Unicode(length=320), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['resource_uid'], ['resources.uid'], ),
    sa.PrimaryKeyConstraint('resource_uid')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('asset_classifications')
    with op.batch_alter_table('rules') as batch:
        batch.drop_column('reference_urls')
        batch.drop_column('detection')
        batch.drop_column('description')
