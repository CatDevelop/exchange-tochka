from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.current_user import get_current_user, is_user_admin
from app.core.db import get_async_session
from app.crud.v1.user import user_crud
from app.schemas.user import (
    UserRegister, UserResponse,
)

router = APIRouter()


@router.post(
    '/public/register',
    summary='Регистрация пользователя',
    tags=['public']
)
async def register_user(
        body: UserRegister,
        session: AsyncSession = Depends(get_async_session),
) -> UserResponse:
    user = await user_crud.add_user(body.name, session)
    return UserResponse.model_validate(user)


@router.get(
    '/public/profile',
    summary='Получение профиля пользователя',
    tags=['public']
)
async def get_profile_user(
        current_user: AsyncSession = Depends(get_current_user),
) -> UserResponse:
    user = UserResponse.model_validate(current_user)
    return user
