from sqlalchemy import Column, String, Numeric, ForeignKey, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from decimal import Decimal
from sqlalchemy import PrimaryKeyConstraint

from app.core.db import Base


class Balance(Base):
    __tablename__ = 'balances'
    __table_args__ = (
        PrimaryKeyConstraint('user_id', 'ticker'),
        CheckConstraint('amount >= 0', name='positive_balance'),
    )

    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    ticker = Column(String(10), nullable=False)
    amount = Column(Numeric(20, 10), default=Decimal("0.0"))

    def __repr__(self):
        return f"<Balance user_id={self.user_id} ticker={self.ticker}: {self.amount}>"