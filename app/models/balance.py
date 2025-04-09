from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    ForeignKey,
    Numeric,
    PrimaryKeyConstraint,
    String,
)

from app.core.db import Base


class Balance(Base):
    __table_args__ = (
        PrimaryKeyConstraint('user_id', 'ticker'),
        CheckConstraint('amount >= 0', name='positive_balance'),
    )

    user_id = Column(
        BigInteger, ForeignKey('user.id'), nullable=False, primary_key=True
    )
    ticker = Column(String(10), nullable=False, primary_key=True)
    amount = Column(Numeric(20, 10), default=Decimal('0.0'))

    def __repr__(self):
        return f"<Balance user_id={self.user_id} ticker={self.ticker}: {self.amount}>"
