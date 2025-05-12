import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import UserRole
from app.crud.base import CRUDBase
from app.models.user import User


class CRUDUser(CRUDBase[User]):
    def __init__(self):
        super().__init__(User, primary_key_name='id')

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

    async def get_by_id(self, user_id: int, async_session: AsyncSession | None = None):
        return await self.get(user_id, async_session)

    async def remove(self, user_id: int, async_session: AsyncSession | None = None):
        user = await self.get_by_id(user_id, async_session)
        if not user or user.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail='User not found'
            )
        user.is_deleted = True
        await async_session.flush()
        await async_session.refresh(user)
        await async_session.commit()
        return user


user_crud = CRUDUser()
