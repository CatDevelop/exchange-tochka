from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP

from app.core.db import Base


class Transaction(Base):
    __tablename__ = "transaction"

    id = Column(UUID(as_uuid=False), primary_key=True, default=uuid4)
    user_id = Column(
        UUID(as_uuid=False), ForeignKey('user.id', ondelete="CASCADE"), nullable=False
    )
    ticker = Column(
        String, ForeignKey('instrument.ticker', ondelete="CASCADE"), nullable=False
    )
    amount = Column(Integer, nullable=False)
    price = Column(Integer, nullable=False)
    timestamp = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
