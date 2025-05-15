from typing import Union

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.current_user import get_current_user
from app.core.db import get_async_session
from app.crud.v1.order import order_crud
from app.schemas.order import LimitOrderBody, MarketOrderBody, OrderResponse
from app.models.user import User

router = APIRouter()


@router.post(
    '/order',
    response_model=OrderResponse,
    summary='Создание заявки',
    tags=['order'],
)
async def create_order(
        body: Union[LimitOrderBody, MarketOrderBody],
        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(get_current_user),
):
    try:
        order = await order_crud.create_order(user_id=current_user.id, body=body, session=session)
        return OrderResponse(success=True, order_id=order.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail='Внутренняя ошибка сервера')
