from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    PrimaryKeyConstraint,
    String, Integer,
)
from sqlalchemy.dialects.postgresql import UUID

from app.core.db import Base


class Balance(Base):
    __table_args__ = (
        PrimaryKeyConstraint('user_id', 'ticker'),
        CheckConstraint('amount >= 0', name='positive_balance'),
        CheckConstraint('blocked_amount >= 0', name='positive_blocked_balance'),
        CheckConstraint('blocked_amount <= amount', name='blocked_not_exceed_amount'),
    )

    user_id = Column(
        UUID(as_uuid=False), ForeignKey('user.id', ondelete="CASCADE"), nullable=False, primary_key=True
    )
    ticker = Column(
        String, ForeignKey('instrument.ticker', ondelete="CASCADE"), nullable=False, primary_key=True
    )
    amount = Column(Integer, default=0, nullable=False)
    blocked_amount = Column(Integer, default=0, nullable=True)

    @property
    def available_amount(self):
        """Доступная для использования сумма (общая минус заблокированная)"""
        return self.amount - self.blocked_amount

    def __repr__(self):
        return f"<Balance user_id={self.user_id} ticker={self.ticker}: {self.amount} (blocked: {self.blocked_amount})>"
