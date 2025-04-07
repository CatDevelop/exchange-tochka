from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
import uuid

from app.core.db import Base
from app.core.enums import UserRole


class User(Base):
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False
    )
    name: Mapped[str] = mapped_column(nullable=False)
    role: Mapped[UserRole] = mapped_column(nullable=False, default=UserRole.USER)
    api_key: Mapped[str] = mapped_column(nullable=False, unique=True)