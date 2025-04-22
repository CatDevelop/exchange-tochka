import re
from typing import AsyncGenerator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, declared_attr

from app.core.config import settings


class Base(AsyncAttrs, DeclarativeBase):
    __abstract__ = True

    metadata = MetaData(
        naming_convention={
            'ix': 'ix_%(column_0_label)s',
            'uq': 'uq_%(table_name)s_%(column_0_N_name)s',
            'ck': 'ck_%(table_name)s_%(constraint_name)s',
            'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s',
            'pk': 'pk_%(table_name)s',
        },
    )

    @declared_attr.directive
    def __tablename__(cls) -> str:  # noqa: N805
        name = cls.__name__
        name = re.sub(r'([A-Z]+)(?=[A-Z][a-z]|\d|\W|$)|\B([A-Z])', r'_\1\2', name)
        name = name.lower()
        name = name.lstrip('_')
        name = re.sub(r'_{2,}', '_', name)
        return name


engine = create_async_engine(settings.db.url)


AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as async_session:
        yield async_session
