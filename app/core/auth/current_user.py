from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.db import get_async_session
from app.core.enums import UserRole
from app.models import User

auth_header = APIKeyHeader(name='Authorization', auto_error=True)


async def get_current_user(
    api_key: str = Security(auth_header),
    session: AsyncSession = Depends(get_async_session),
) -> User:
    result = await session.execute(select(User).where(User.api_key == api_key))
    user = result.scalars().first()

    if not user:
        raise HTTPException(status_code=401, detail='Invalid or missing API Key')

    return user


async def is_user_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail='Access forbidden: Admins only')
    return user
