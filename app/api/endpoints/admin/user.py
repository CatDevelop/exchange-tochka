from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.current_user import is_user_admin
from app.core.db import get_async_session
from app.crud.v1.user import user_crud
from app.schemas.user import UserResponse

router = APIRouter()


@router.delete(
    '/admin/user/{user_id}',
    response_model=UserResponse,
    tags=['admin', 'user'],
    dependencies=[Depends(is_user_admin)],
    responses={
        200: {'description': 'User deleted successfully'},
        422: {'description': 'Validation error'},
    },
)
async def delete_user(
    user_id: int,
    session: AsyncSession = Depends(get_async_session),
):
    deleted_user = await user_crud.remove(user_id, session)
    return UserResponse.model_validate(deleted_user)
