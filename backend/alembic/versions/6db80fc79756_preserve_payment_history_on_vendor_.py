"""preserve_payment_history_on_vendor_delete

Revision ID: 6db80fc79756
Revises: d6bd0bf83b8d
Create Date: 2026-08-21 01:27:54.778008

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6db80fc79756'
down_revision: Union[str, Sequence[str], None] = 'd6bd0bf83b8d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to preserve payment history when a vendor is deleted."""
    # 1. vendor_remittances: Allow NULL vendor_id and SET NULL on vendor delete
    op.alter_column('vendor_remittances', 'vendor_id', nullable=True)
    op.drop_constraint('vendor_remittances_vendor_id_fkey', 'vendor_remittances', type_='foreignkey')
    op.create_foreign_key(
        'vendor_remittances_vendor_id_fkey',
        'vendor_remittances',
        'vendors',
        ['vendor_id'],
        ['id'],
        ondelete='SET NULL'
    )

    # 2. payments: Allow NULL vendor_id and SET NULL on vendor delete
    op.alter_column('payments', 'vendor_id', nullable=True)
    op.drop_constraint('payments_vendor_id_fkey', 'payments', type_='foreignkey')
    op.create_foreign_key(
        'payments_vendor_id_fkey',
        'payments',
        'vendors',
        ['vendor_id'],
        ['id'],
        ondelete='SET NULL'
    )

    # 3. vendor_change_requests: Allow NULL vendor_id and SET NULL on vendor delete
    op.alter_column('vendor_change_requests', 'vendor_id', nullable=True)
    op.drop_constraint('vendor_change_requests_vendor_id_fkey', 'vendor_change_requests', type_='foreignkey')
    op.create_foreign_key(
        'vendor_change_requests_vendor_id_fkey',
        'vendor_change_requests',
        'vendors',
        ['vendor_id'],
        ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    """Downgrade schema."""
    # 1. vendor_change_requests
    op.drop_constraint('vendor_change_requests_vendor_id_fkey', 'vendor_change_requests', type_='foreignkey')
    op.create_foreign_key(
        'vendor_change_requests_vendor_id_fkey',
        'vendor_change_requests',
        'vendors',
        ['vendor_id'],
        ['id'],
        ondelete='CASCADE'
    )
    op.alter_column('vendor_change_requests', 'vendor_id', nullable=False)

    # 2. payments
    op.drop_constraint('payments_vendor_id_fkey', 'payments', type_='foreignkey')
    op.create_foreign_key(
        'payments_vendor_id_fkey',
        'payments',
        'vendors',
        ['vendor_id'],
        ['id'],
        ondelete='RESTRICT'
    )
    op.alter_column('payments', 'vendor_id', nullable=False)

    # 3. vendor_remittances
    op.drop_constraint('vendor_remittances_vendor_id_fkey', 'vendor_remittances', type_='foreignkey')
    op.create_foreign_key(
        'vendor_remittances_vendor_id_fkey',
        'vendor_remittances',
        'vendors',
        ['vendor_id'],
        ['id'],
        ondelete='CASCADE'
    )
    op.alter_column('vendor_remittances', 'vendor_id', nullable=False)
