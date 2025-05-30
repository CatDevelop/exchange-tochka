"""cascade delete balance by user delete

Revision ID: ae663042214b
Revises: ae60731d6fc6
Create Date: 2025-05-15 16:11:38.421994

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ae663042214b'
down_revision: Union[str, None] = 'ae60731d6fc6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        'transaction',
        sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('user_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('ticker', sa.String(), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('price', sa.Integer(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['user.id'],
            name=op.f('fk_transaction_user_id_user'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_transaction')),
    )
    op.drop_constraint('fk_balance_user_id_user', 'balance', type_='foreignkey')
    op.create_foreign_key(
        op.f('fk_balance_user_id_user'),
        'balance',
        'user',
        ['user_id'],
        ['id'],
        ondelete='CASCADE',
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(op.f('fk_balance_user_id_user'), 'balance', type_='foreignkey')
    op.create_foreign_key(
        'fk_balance_user_id_user', 'balance', 'user', ['user_id'], ['id']
    )
    op.drop_table('transaction')
    # ### end Alembic commands ###
