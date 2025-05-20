from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.current_user import get_current_user
from app.core.db import get_async_session
from app.crud.v1.user import user_crud
from app.schemas.user import NewUser, User

router = APIRouter()


@router.post('/public/register', summary='Регистрация пользователя', tags=['public'])
async def register_user(
    body: NewUser,
    session: AsyncSession = Depends(get_async_session),
) -> User:
    try:
        user = await user_crud.add_user(body.name, session)
        return User.model_validate(user)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера register_user: {str(e)}")


@router.get(
    '/public/profile', summary='Получение профиля пользователя', tags=['public']
)
async def get_profile_user(
    current_user: AsyncSession = Depends(get_current_user),
) -> User:
    try:
        user = User.model_validate(current_user)
        return user
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера get_profile_user: {str(e)}")
