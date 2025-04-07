"""remove balance from user and create balances table

Revision ID: afd451ece05c
Revises: a8a53aa419ce
Create Date: 2025-04-07 21:51:05.244462
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from decimal import Decimal

# revision identifiers, used by Alembic
revision: str = 'afd451ece05c'
down_revision: Union[str, None] = 'a8a53aa419ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.execute('ALTER TABLE users ALTER COLUMN id TYPE UUID USING id::uuid')

    op.create_table(
        'balances',
        sa.Column('user_id', UUID(as_uuid=True),
                 sa.ForeignKey('users.id'), nullable=False),
        sa.Column('ticker', sa.String(10), nullable=False),
        sa.Column('amount', sa.Numeric(20, 10),
                 server_default=str(Decimal("0.0")), nullable=False),
        sa.PrimaryKeyConstraint('user_id', 'ticker'),
        sa.CheckConstraint('amount >= 0', name='positive_balance'),
        comment='Балансы пользователей'
    )

    op.execute("""
        INSERT INTO balances (user_id, ticker, amount)
        SELECT id, 'RUB', balance 
        FROM users
        WHERE balance > 0
    """)

    op.drop_column('users', 'balance')


def downgrade():
    op.add_column(
        'users',
        sa.Column('balance', sa.Numeric(20, 10),
                 server_default=str(Decimal("0.0")), nullable=False)
    )

    op.execute("""
        UPDATE users u
        SET balance = COALESCE(
            (SELECT amount FROM balances b 
             WHERE b.user_id = u.id::text::uuid AND b.ticker = 'RUB'), 
            0
        )
    """)

    op.drop_table('balances')

    op.execute('ALTER TABLE users ALTER COLUMN id TYPE BIGINT USING id::text::bigint')