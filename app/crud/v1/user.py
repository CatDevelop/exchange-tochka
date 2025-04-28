import uuid

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
            name=name, role=UserRole.USER, api_key=f"key-{uuid.uuid4()}"
        )
        async_session.add(new_user)
        await async_session.flush()
        await async_session.refresh(new_user)
        await async_session.commit()
        return new_user

    async def get(self, user_id: int, async_session: AsyncSession | None = None):
        return await async_session.get(self.model, user_id)

    async def remove(self, user_id: int, async_session: AsyncSession | None = None):
        user = await self.get(user_id)
        if user:
            await async_session.delete(user)
            await async_session.commit()
        return user


user_crud = CRUDUser(User)
