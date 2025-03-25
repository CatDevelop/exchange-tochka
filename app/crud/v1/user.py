import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import UserRole
from app.crud.base import CRUDBase
from app.models.user import User


class CRUDUser(CRUDBase[User]):
    async def add_user(
            self,
            name: str = '',
            async_session: AsyncSession | None = None,
    ) -> User:
        new_user = self.model(
            name=name,
            role=UserRole.USER,
            api_key=f"key-{uuid.uuid4()}",
            balance=Decimal("0.0")
        )
        async_session.add(new_user)
        await async_session.flush()
        await async_session.refresh(new_user)
        await async_session.commit()
        return new_user


user_crud = CRUDUser(User)
