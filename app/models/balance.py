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
    )

    user_id = Column(
        UUID(as_uuid=False), ForeignKey('user.id'), nullable=False, primary_key=True
    )
    ticker = Column(
        String, ForeignKey('instrument.ticker'), nullable=False, primary_key=True
    )
    amount = Column(Integer, default=0, nullable=False)

    def __repr__(self):
        return f"<Balance user_id={self.user_id} ticker={self.ticker}: {self.amount}>"
