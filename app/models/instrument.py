from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Instrument(Base):
    Base.__tablename__ = 'instrument'

    ticker: Mapped[str] = mapped_column(nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(nullable=False)

    def __repr__(self):
        return f"<Instrument ticker={self.ticker}, name={self.name}>"
