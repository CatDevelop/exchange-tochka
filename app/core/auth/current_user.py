from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.db import get_async_session
from app.core.enums import UserRole
from app.models import User

auth_header = APIKeyHeader(name='Authorization', auto_error=True)


async def get_api_key(api_key_header: str = Depends(auth_header)):
    try:
        scheme, _, api_key = api_key_header.partition(' ')
        if scheme.lower() != 'token':
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return api_key.strip()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Неверная схема авторизации',
        )


async def get_current_user(
    api_key: str = Depends(get_api_key),
    session: AsyncSession = Depends(get_async_session),
) -> User:
    result = await session.execute(select(User).where(User.api_key == api_key))
    user = result.scalars().first()

    if not user or user.is_deleted:
        raise HTTPException(status_code=401, detail='Invalid or missing API Key')

    return user


async def is_user_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail='Access forbidden: Admins only')
    return user
