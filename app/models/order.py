import enum
from uuid import uuid4

from sqlalchemy import Column, String, Integer, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import validates

from app.core.db import Base


class OrderStatus(enum.Enum):
    NEW = "NEW"
    EXECUTED = "EXECUTED"
    PARTIALLY_EXECUTED = "PARTIALLY_EXECUTED"
    CANCELLED = "CANCELLED"


class OrderDirection(enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


# Модель Order
class Order(Base):
    __tablename__ = "order"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    status = Column(Enum(OrderStatus), nullable=False)
    user_id = Column(
        UUID(as_uuid=False), ForeignKey('user.id', ondelete="CASCADE"), nullable=False
    )
    direction = Column(Enum(OrderDirection), nullable=False)
    ticker = Column(
        String,
        ForeignKey("instrument.ticker", ondelete="CASCADE"),
        nullable=False,
    )
    qty = Column(Integer, nullable=False)
    price = Column(Integer, nullable=True)
    filled = Column(Integer, nullable=True)

    @validates("price")
    def validate_non_negative(self, key, value):
        if value is not None and value < 0:
            raise ValueError(f"{key} must be non-negative")
        return value

    @validates("qty")
    def validate_qte(self, key, value):
        if value is not None and value < 1:
            raise ValueError(f"{key} must be grater than or equal 1")
        return value
