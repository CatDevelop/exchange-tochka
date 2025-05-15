from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logs.logs import error_log
from app.crud.base import CRUDBase
from app.models import Order
from app.models.order import OrderStatus


class CRUDOrderBase(CRUDBase[Order]):
    """Базовый класс для работы с ордерами"""
    
    def __init__(self):
        super().__init__(Order, primary_key_name='id')
        
    @error_log
    async def get(
        self,
        id: str,
        session: AsyncSession,
    ) -> Order:
        """Получение заявки по ID"""
        result = await session.execute(
            select(Order).where(Order.id == id)
        )
        return result.scalar_one_or_none()

    @error_log
    async def get_user_orders(
        self,
        user_id: str,
        session: AsyncSession,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Order]:
        """Получение списка заявок пользователя"""
        result = await session.execute(
            select(Order)
            .where(Order.user_id == user_id)
            .order_by(Order.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    @error_log
    async def get_all_orders(
        self,
        session: AsyncSession,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Order]:
        """Получение списка всех заявок"""
        result = await session.execute(
            select(Order)
            .order_by(Order.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all() 