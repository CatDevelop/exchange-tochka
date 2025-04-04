from decimal import Decimal

from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.enums import UserRole


class User(Base):
    name: Mapped[str] = mapped_column(nullable=False)
    role: Mapped[UserRole] = mapped_column(nullable=False, default=UserRole.USER)
    api_key: Mapped[str] = mapped_column(nullable=False, unique=True)
    balance: Mapped[Decimal] = mapped_column(nullable=False, default=Decimal("0.0"))