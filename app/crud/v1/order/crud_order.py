from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logs.logs import error_log
from app.models import Order
from app.models.order import OrderDirection, OrderStatus
from app.schemas.order import LimitOrderBody, MarketOrderBody
from app.crud.v1.balance import balance_crud

from app.crud.v1.order.base import CRUDOrderBase
from app.crud.v1.order.balance_operations import (
    lock_balance_row, 
    block_funds, 
    block_assets, 
    add_assets,
    add_funds,
    deduct_funds,
    deduct_assets
)
from app.crud.v1.order.matching_engine import match_sell_orders, match_buy_orders
from app.crud.v1.order.market_data import get_orderbook


class CRUDOrder(CRUDOrderBase):
    """Класс для работы с ордерами"""

    @error_log
    async def create_order(
            self,
            user_id: str,
            body: LimitOrderBody | MarketOrderBody,
            session: AsyncSession,
    ) -> Order:
        """Создание нового ордера с учетом сопоставления с существующими ордерами"""
        order_id = str(uuid4())
        is_limit = body.price is not None
        direction = body.direction
        ticker = body.ticker
        qty = body.qty
        price = getattr(body, 'price', None)

        filled = 0
        spent_money = 0
        earned_money = 0
        
        # Сначала блокируем Order-таблицу заранее, чтобы предотвратить deadlock
        # Создаем пустой ордер со статусом PENDING, чтобы зарезервировать ID в таблице заказов
        pending_order = Order(
            id=order_id,
            status=OrderStatus.NEW,  # Временный статус
            user_id=user_id,
            direction=direction,
            ticker=ticker,
            qty=qty,
            price=price,
            filled=0,
        )
        session.add(pending_order)
        await session.flush()  # Фиксируем в БД, но без коммита
        
        # Теперь блокируем балансы в строго определенном порядке
        try:
            # Блокируем баланс RUB
            await lock_balance_row(user_id, "RUB", session)
            
            # Затем блокируем баланс тикера, если он отличается от RUB
            if ticker != "RUB":
                await lock_balance_row(user_id, ticker, session)
        except Exception as e:
            error_log(f"Ошибка при блокировке балансов: {str(e)}")
            # Откатываем создание ордера при ошибке
            pending_order.status = OrderStatus.CANCELLED
            await session.commit()
            raise ValueError(f"Не удалось заблокировать балансы: {str(e)}")

        # Проверка достаточности баланса перед созданием ордера
        if direction == OrderDirection.BUY and is_limit:
            # Для покупки проверяем достаточно ли RUB
            required_amount = qty * price
            available_rub = await balance_crud.get_user_available_balance(user_id, "RUB", session)
            if available_rub < required_amount:
                # Отменяем ордер при недостаточном балансе
                pending_order.status = OrderStatus.CANCELLED
                await session.commit()
                raise ValueError(f"Недостаточно средств для создания ордера на покупку. Требуется: {required_amount} RUB, доступно: {available_rub} RUB")
        
        elif direction == OrderDirection.SELL:
            # Для продажи проверяем достаточно ли актива
            available_asset = await balance_crud.get_user_available_balance(user_id, ticker, session)
            if available_asset < qty:
                # Отменяем ордер при недостаточном балансе
                pending_order.status = OrderStatus.CANCELLED
                await session.commit()
                raise ValueError(f"Недостаточно средств для создания ордера на продажу. Требуется: {qty} {ticker}, доступно: {available_asset} {ticker}")

        if direction == OrderDirection.BUY:
            # Пытаемся сопоставить с заявками на продажу
            matched_orders = await match_sell_orders(ticker, qty, price, session)
            filled = matched_orders["filled_qty"]
            spent_money = matched_orders["spent_money"]

            # Если некоторое количество было исполнено, обрабатываем это
            if filled > 0:
                # Передаём купленные активы покупателю
                await add_assets(user_id, filled, ticker, session)
                # Списываем деньги с покупателя
                await deduct_funds(user_id, spent_money, "RUB", session)
            
            if not is_limit:
                # Рыночная заявка
                if filled == 0:
                    # Если не исполнилась совсем, создаем с CANCELLED
                    status = OrderStatus.CANCELLED
                elif filled < qty:
                    # Частично исполнилась - оставшуюся часть отменяем
                    status = OrderStatus.PARTIALLY_EXECUTED
                else:
                    # Полностью исполнилась
                    status = OrderStatus.EXECUTED
            else:
                # Лимитная заявка
                if filled < qty:
                    # Блокируем средства для оставшейся части заявки
                    remaining_cost = (qty - filled) * price
                    await block_funds(user_id, remaining_cost, "RUB", session)
                
                status = (
                    OrderStatus.EXECUTED if filled == qty
                    else OrderStatus.PARTIALLY_EXECUTED if filled > 0
                    else OrderStatus.NEW
                )
        elif direction == OrderDirection.SELL:
            # Пытаемся сопоставить с заявками на покупку
            matched_orders = await match_buy_orders(ticker, qty, price, session)
            filled = matched_orders["filled_qty"]
            earned_money = matched_orders["earned_money"]

            # Если некоторое количество было исполнено
            if filled > 0:
                # Списываем проданные активы у продавца
                await deduct_assets(user_id, filled, ticker, session)
                # Добавляем деньги продавцу
                await add_funds(user_id, earned_money, "RUB", session)

            if not is_limit:
                # Рыночная заявка
                if filled == 0:
                    # Если не исполнилась совсем, создаем с CANCELLED
                    status = OrderStatus.CANCELLED
                elif filled < qty:
                    # Частично исполнилась - оставшуюся часть отменяем
                    status = OrderStatus.PARTIALLY_EXECUTED
                else:
                    # Полностью исполнилась
                    status = OrderStatus.EXECUTED
            else:
                # Лимитная заявка
                if filled < qty:
                    # Блокируем активы для оставшейся части заявки
                    remaining_qty = qty - filled
                    await block_assets(user_id, remaining_qty, ticker, session)
                
                status = (
                    OrderStatus.EXECUTED if filled == qty
                    else OrderStatus.PARTIALLY_EXECUTED if filled > 0
                    else OrderStatus.NEW
                )

        # Обновляем статус ордера
        pending_order.status = status
        pending_order.filled = filled
        
        await session.commit()
        return pending_order

    @error_log
    async def update_order_status(
        self,
        order_id: str,
        new_status: OrderStatus,
        session: AsyncSession,
    ) -> Order:
        """Обновление статуса заявки с разблокировкой средств при необходимости"""
        # Сначала блокируем балансы, потом ордер - это обеспечивает одинаковый порядок блокировок
        # Получаем ордер, но без блокировки сначала, чтобы узнать user_id и ticker
        result = await session.execute(
            select(Order).where(Order.id == order_id)
        )
        order_info = result.scalar_one_or_none()
        
        if not order_info:
            raise ValueError(f"Заявка с ID {order_id} не найдена")
            
        # Блокируем балансы в строго определенном порядке
        await lock_balance_row(order_info.user_id, "RUB", session)
        if order_info.ticker != "RUB":
            await lock_balance_row(order_info.user_id, order_info.ticker, session)
        
        # Теперь блокируем сам ордер
        result = await session.execute(
            select(Order).where(Order.id == order_id).with_for_update()
        )
        order = result.scalar_one_or_none()
        
        # Если ордер уже не существует
        if not order:
            raise ValueError(f"Заявка с ID {order_id} не найдена")
        
        # Если статус не изменился, просто возвращаем заявку
        if order.status == new_status:
            return order
        
        # Если заявка уже отменена или исполнена, не позволяем менять статус
        if order.status in [OrderStatus.CANCELLED, OrderStatus.EXECUTED]:
            raise ValueError(f"Нельзя изменить статус заявки в статусе {order.status}")
        
        old_status = order.status
        order.status = new_status
        
        # Если заявка отменяется или исполняется полностью, разблокируем средства
        if new_status in [OrderStatus.CANCELLED, OrderStatus.EXECUTED]:                
            if order.direction == OrderDirection.BUY:
                # Разблокируем деньги у покупателя только для лимитных ордеров
                # Для рыночных ордеров price будет None
                remaining_qty = order.qty - (order.filled or 0)
                if remaining_qty > 0 and order.price is not None:
                    remaining_cost = remaining_qty * order.price
                    try:
                        await balance_crud.unblock_funds(order.user_id, "RUB", remaining_cost, session)
                        error_log(f"Разблокировано средств: {remaining_cost} RUB для пользователя {order.user_id}")
                    except ValueError as e:
                        error_log(f"Ошибка при разблокировке средств: {str(e)}")
            
            elif order.direction == OrderDirection.SELL:
                # Разблокируем активы у продавца только для лимитных ордеров
                # Для рыночных ордеров нет заблокированных активов
                remaining_qty = order.qty - (order.filled or 0)
                if remaining_qty > 0 and order.price is not None:
                    try:
                        await balance_crud.unblock_assets(order.user_id, order.ticker, remaining_qty, session)
                        error_log(f"Разблокировано активов: {remaining_qty} {order.ticker} для пользователя {order.user_id}")
                    except ValueError as e:
                        error_log(f"Ошибка при разблокировке активов: {str(e)}")
        
        await session.commit()
        return order

    async def get_orderbook(self, ticker: str, session: AsyncSession, limit: int = 100) -> dict:
        """Получение биржевого стакана - делегируем в специализированный модуль"""
        return await get_orderbook(ticker, session, limit)


# Создаем единственный экземпляр для использования в приложении
order_crud = CRUDOrder() 