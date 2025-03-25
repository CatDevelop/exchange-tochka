from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

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
