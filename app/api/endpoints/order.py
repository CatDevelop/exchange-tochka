from typing import Union, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.current_user import get_current_user, is_user_admin
from app.core.db import get_async_session
from app.crud.v1.order import order_crud
from app.schemas.order import (
    LimitOrderBody, 
    MarketOrderBody, 
    OrderResponse, 
    CancelOrderResponse, 
    OrderDetailResponse,
    OrderBodyResponse
)
from app.models.user import User
from app.models.order import OrderStatus, OrderDirection

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


@router.get(
    '/order',
    response_model=List[OrderDetailResponse],
    summary='Получение списка всех заявок',
    tags=['order'],
)
async def get_all_orders(
        limit: Optional[int] = Query(100, ge=1, le=1000, description="Максимальное количество заявок"),
        offset: Optional[int] = Query(0, ge=0, description="Смещение от начала списка"),
        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(get_current_user),
):
    try:
        db_orders = await order_crud.get_all_orders(
            session=session,
            limit=limit,
            offset=offset
        )
        
        orders = []
        for order in db_orders:
            # Создаем тело ордера в зависимости от наличия цены
            order_body = OrderBodyResponse(
                direction=order.direction,
                ticker=order.ticker,
                qty=order.qty,
                price=order.price
            )
            
            # Создаем ответ по каждому ордеру
            orders.append(OrderDetailResponse(
                id=order.id,
                status=order.status,
                user_id=order.user_id,
                timestamp=order.created_at,
                body=order_body,
                filled=order.filled or 0
            ))
        
        return orders
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера: {str(e)}")


@router.get(
    '/order/{order_id}',
    response_model=OrderDetailResponse,
    summary='Получение информации о конкретной заявке',
    tags=['order'],
)
async def get_order_by_id(
        order_id: str = Path(..., description="ID заявки"),
        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(get_current_user),
):
    try:
        order = await order_crud.get(id=order_id, session=session)
        
        if not order:
            raise HTTPException(status_code=404, detail='Заявка не найдена')
        
        # Создаем тело ордера
        order_body = OrderBodyResponse(
            direction=order.direction,
            ticker=order.ticker,
            qty=order.qty,
            price=order.price
        )
        
        # Формируем ответ
        return OrderDetailResponse(
            id=order.id,
            status=order.status,
            user_id=order.user_id,
            timestamp=order.created_at,
            body=order_body,
            filled=order.filled or 0
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера: {str(e)}")
