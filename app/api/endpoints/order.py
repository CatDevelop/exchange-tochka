from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.current_user import get_current_user
from app.core.db import get_async_session
from app.crud.v1.order import order_crud
from app.schemas.order import LimitOrderBody, MarketOrderBody, OrderResponse, CancelOrderResponse
from app.models.user import User
from app.models.order import OrderStatus

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
    except Exception as e:
        raise HTTPException(status_code=500, detail='Внутренняя ошибка сервера')


@router.delete(
    '/order/{order_id}',
    response_model=CancelOrderResponse,
    summary='Отмена заявки',
    tags=['order'],
)
async def cancel_order(
        order_id: str = Path(..., description="ID заявки для отмены"),
        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(get_current_user),
):
    try:
        # Получаем заявку для проверки прав
        order = await order_crud.get(id=order_id, session=session)
        
        if not order:
            raise HTTPException(status_code=404, detail='Заявка не найдена')
        
        # Проверяем, что пользователь является владельцем заявки
        if order.user_id != current_user.id:
            raise HTTPException(status_code=403, detail='Нет доступа к этой заявке')
        
        # Отменяем заявку
        updated_order = await order_crud.update_order_status(
            order_id=order_id,
            new_status=OrderStatus.CANCELLED,
            session=session
        )
        
        return CancelOrderResponse(success=True, order_id=updated_order.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Внутренняя ошибка сервера: {str(e)}')
