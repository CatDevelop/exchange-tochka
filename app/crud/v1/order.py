from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logs.logs import error_log
from app.crud.base import CRUDBase
from app.models import Order, Transaction
from app.models.balance import Balance
from app.models.order import OrderDirection, OrderStatus
from app.schemas.order import LimitOrderBody, MarketOrderBody
from app.crud.v1.balance import balance_crud


class CRUDOrder(CRUDBase[Order]):
    def __init__(self):
        super().__init__(Order, primary_key_name='id')

    @error_log
    async def create_order(
            self,
            user_id: str,
            body: LimitOrderBody | MarketOrderBody,
            session: AsyncSession,
    ) -> Order:
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
            await self._lock_balance_row(user_id, "RUB", session)
            
            # Затем блокируем баланс тикера, если он отличается от RUB
            if ticker != "RUB":
                await self._lock_balance_row(user_id, ticker, session)
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
            matched_orders = await self._match_sell_orders(ticker, qty, price, session)
            filled = matched_orders["filled_qty"]
            spent_money = matched_orders["spent_money"]

            # Если некоторое количество было исполнено, обрабатываем это
            if filled > 0:
                # Передаём купленные активы покупателю
                await self._add_assets(user_id, filled, ticker, session)
                # Списываем деньги с покупателя
                await self._deduct_funds(user_id, spent_money, "RUB", session)
            
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
                    await self._block_funds(user_id, remaining_cost, "RUB", session)
                
                status = (
                    OrderStatus.EXECUTED if filled == qty
                    else OrderStatus.PARTIALLY_EXECUTED if filled > 0
                    else OrderStatus.NEW
                )
        elif direction == OrderDirection.SELL:
            # Пытаемся сопоставить с заявками на покупку
            matched_orders = await self._match_buy_orders(ticker, qty, price, session)
            filled = matched_orders["filled_qty"]
            earned_money = matched_orders["earned_money"]

            # Если некоторое количество было исполнено
            if filled > 0:
                # Списываем проданные активы у продавца
                await self._deduct_assets(user_id, filled, ticker, session)
                # Добавляем деньги продавцу
                await self._add_funds(user_id, earned_money, "RUB", session)

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
                    await self._block_assets(user_id, remaining_qty, ticker, session)
                
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

    async def _lock_balance_row(self, user_id: str, ticker: str, session: AsyncSession):
        """Блокирует строку баланса для предотвращения deadlock"""
        error_log(f"Блокировка строки баланса: user_id={user_id}, ticker={ticker}")
        # SELECT ... FOR UPDATE гарантирует эксклюзивную блокировку строки
        await session.execute(
            select(Balance)
            .where(Balance.user_id == user_id, Balance.ticker == ticker)
            .with_for_update()
        )

    async def _match_sell_orders(self, ticker: str, qty: int, price: int | None, session: AsyncSession) -> dict:
        # Сначала получаем все подходящие ордера
        query = select(Order).where(
            Order.ticker == ticker,
            Order.direction == OrderDirection.SELL,
            Order.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]),
        ).order_by(Order.price.asc().nulls_last())

        if price is not None:
            query = query.where(Order.price <= price)

        # Используем FOR UPDATE SKIP LOCKED для избежания deadlock
        query = query.with_for_update(skip_locked=True)

        result = await session.execute(query)
        sell_orders = result.scalars().all()

        filled_qty = 0
        spent_money = 0

        for sell_order in sell_orders:
            # Блокируем балансы продавца в строго определенном порядке
            # Всегда сначала RUB, затем тикер - это предотвращает deadlock
            await self._lock_balance_row(sell_order.user_id, "RUB", session)
            if ticker != "RUB":
                await self._lock_balance_row(sell_order.user_id, ticker, session)

            remaining = sell_order.qty - (sell_order.filled or 0)
            to_fill = min(qty - filled_qty, remaining)

            if to_fill <= 0:
                continue

            sell_order.filled = (sell_order.filled or 0) + to_fill
            sell_order.status = (
                OrderStatus.EXECUTED
                if sell_order.filled == sell_order.qty
                else OrderStatus.PARTIALLY_EXECUTED
            )

            filled_qty += to_fill
            order_price = sell_order.price
            order_cost = to_fill * order_price
            spent_money += order_cost
            
            # Зачисляем деньги продавцу
            await self._add_funds(sell_order.user_id, order_cost, "RUB", session)
            
            # Разблокируем активы продавца, если это лимитная заявка
            if sell_order.price is not None:
                # Разблокировка активов
                try:
                    await balance_crud.unblock_assets(sell_order.user_id, ticker, to_fill, session)
                    error_log(f"Разблокировано активов: {to_fill} {ticker} для пользователя {sell_order.user_id}")
                except ValueError as e:
                    error_log(f"Ошибка при разблокировке активов: {str(e)}")

            await self._create_transaction(
                user_id=sell_order.user_id,
                ticker=ticker,
                amount=to_fill,
                price=sell_order.price,
                session=session,
            )

            if filled_qty == qty:
                break

        return {"filled_qty": filled_qty, "spent_money": spent_money}

    async def _match_buy_orders(self, ticker: str, qty: int, price: int | None, session: AsyncSession) -> dict:
        # Сначала получаем все подходящие ордера
        query = select(Order).where(
            Order.ticker == ticker,
            Order.direction == OrderDirection.BUY,
            Order.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]),
        ).order_by(Order.price.desc().nulls_last())

        if price is not None:
            query = query.where(Order.price >= price)

        # Используем FOR UPDATE SKIP LOCKED для избежания deadlock
        query = query.with_for_update(skip_locked=True)

        result = await session.execute(query)
        buy_orders = result.scalars().all()

        filled_qty = 0
        earned_money = 0

        for buy_order in buy_orders:
            # Блокируем балансы покупателя в строго определенном порядке
            # Всегда сначала RUB, затем тикер - это предотвращает deadlock
            await self._lock_balance_row(buy_order.user_id, "RUB", session)
            if ticker != "RUB":
                await self._lock_balance_row(buy_order.user_id, ticker, session)

            remaining = buy_order.qty - (buy_order.filled or 0)
            to_fill = min(qty - filled_qty, remaining)

            if to_fill <= 0:
                continue

            buy_order.filled = (buy_order.filled or 0) + to_fill
            buy_order.status = (
                OrderStatus.EXECUTED
                if buy_order.filled == buy_order.qty
                else OrderStatus.PARTIALLY_EXECUTED
            )

            filled_qty += to_fill
            order_price = buy_order.price
            order_cost = to_fill * order_price
            earned_money += order_cost
            
            # Зачисляем актив покупателю
            await self._add_assets(buy_order.user_id, to_fill, ticker, session)
            
            # Разблокируем и списываем деньги у покупателя, если это лимитная заявка
            if buy_order.price is not None:
                # Разблокировка средств
                try:
                    await balance_crud.unblock_funds(buy_order.user_id, "RUB", order_cost, session)
                    error_log(f"Разблокировано средств: {order_cost} RUB для пользователя {buy_order.user_id}")
                except ValueError as e:
                    error_log(f"Ошибка при разблокировке средств: {str(e)}")
            
            await self._create_transaction(
                user_id=buy_order.user_id,
                ticker=ticker,
                amount=to_fill,
                price=buy_order.price,
                session=session,
            )

            if filled_qty == qty:
                break

        return {"filled_qty": filled_qty, "earned_money": earned_money}

    async def _deduct_funds(self, user_id: str, amount: int, ticker: str, session: AsyncSession):
        error_log(f"Списание средств: user_id={user_id}, ticker={ticker}, amount={amount}")
        await session.execute(
            Balance.__table__.update()
            .where(Balance.user_id == user_id, Balance.ticker == ticker)
            .values(amount=Balance.amount - amount)
        )

    async def _block_funds(self, user_id: str, amount: int, ticker: str, session: AsyncSession):
        """Блокировка денежных средств для лимитного ордера на покупку"""
        try:
            await balance_crud.block_funds(user_id, ticker, amount, session)
        except ValueError as e:
            # Логируем ошибку, но не прерываем выполнение
            # В реальном приложении здесь может быть обработка ошибки
            error_log(f"Ошибка блокировки средств: {str(e)}")
        
    async def _block_assets(self, user_id: str, qty: int, ticker: str, session: AsyncSession):
        """Блокировка активов для лимитного ордера на продажу"""
        try:
            await balance_crud.block_assets(user_id, ticker, qty, session)
        except ValueError as e:
            # Логируем ошибку, но не прерываем выполнение
            error_log(f"Ошибка блокировки активов: {str(e)}")

    async def _refund_user(self, user_id: str, amount: int, ticker: str, session: AsyncSession):
        error_log(f"Возврат средств: user_id={user_id}, ticker={ticker}, amount={amount}")
        await session.execute(
            Balance.__table__.update()
            .where(Balance.user_id == user_id, Balance.ticker == ticker)
            .values(amount=Balance.amount + amount)
        )

    async def _deduct_assets(self, user_id: str, qty: int, ticker: str, session: AsyncSession):
        error_log(f"Списание активов: user_id={user_id}, ticker={ticker}, qty={qty}")
        await session.execute(
            Balance.__table__.update()
            .where(Balance.user_id == user_id, Balance.ticker == ticker)
            .values(amount=Balance.amount - qty)
        )
        
    async def _add_assets(self, user_id: str, qty: int, ticker: str, session: AsyncSession):
        error_log(f"Начисление активов: user_id={user_id}, ticker={ticker}, qty={qty}")
        # Проверяем, существует ли запись баланса
        result = await session.execute(
            select(Balance).where(
                Balance.user_id == user_id,
                Balance.ticker == ticker
            )
        )
        balance = result.scalars().first()
        
        if balance:
            # Если запись существует, обновляем её
            error_log(f"Обновление существующего баланса активов: было {balance.amount}, будет {balance.amount + qty}")
            await session.execute(
                Balance.__table__.update()
                .where(Balance.user_id == user_id, Balance.ticker == ticker)
                .values(amount=Balance.amount + qty)
            )
        else:
            # Если записи нет, создаём новую
            error_log(f"Создание нового баланса активов: {qty}")
            new_balance = Balance(user_id=user_id, ticker=ticker, amount=qty, blocked_amount=0)
            session.add(new_balance)

    async def _add_funds(self, user_id: str, amount: int, ticker: str, session: AsyncSession):
        error_log(f"Начисление средств: user_id={user_id}, ticker={ticker}, amount={amount}")
        # Проверяем, существует ли запись баланса
        result = await session.execute(
            select(Balance).where(
                Balance.user_id == user_id,
                Balance.ticker == ticker
            )
        )
        balance = result.scalars().first()
        
        if balance:
            # Если запись существует, обновляем её
            error_log(f"Обновление существующего баланса средств: было {balance.amount}, будет {balance.amount + amount}")
            await session.execute(
                Balance.__table__.update()
                .where(Balance.user_id == user_id, Balance.ticker == ticker)
                .values(amount=Balance.amount + amount)
            )
        else:
            # Если записи нет, создаём новую
            error_log(f"Создание нового баланса средств: {amount}")
            new_balance = Balance(user_id=user_id, ticker=ticker, amount=amount, blocked_amount=0)
            session.add(new_balance)

    async def _create_transaction(self, user_id: str, ticker: str, amount: int, price: int, session: AsyncSession):
        transaction = Transaction(
            id=str(uuid4()),
            user_id=user_id,
            ticker=ticker,
            amount=amount,
            price=price,
            timestamp=datetime.utcnow(),
        )
        session.add(transaction)

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
        await self._lock_balance_row(order_info.user_id, "RUB", session)
        if order_info.ticker != "RUB":
            await self._lock_balance_row(order_info.user_id, order_info.ticker, session)
        
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
                # Разблокируем деньги у покупателя
                remaining_qty = order.qty - (order.filled or 0)
                if remaining_qty > 0 and order.price is not None:
                    remaining_cost = remaining_qty * order.price
                    try:
                        await balance_crud.unblock_funds(order.user_id, "RUB", remaining_cost, session)
                        error_log(f"Разблокировано средств: {remaining_cost} RUB для пользователя {order.user_id}")
                    except ValueError as e:
                        error_log(f"Ошибка при разблокировке средств: {str(e)}")
            
            elif order.direction == OrderDirection.SELL:
                # Разблокируем активы у продавца
                remaining_qty = order.qty - (order.filled or 0)
                if remaining_qty > 0:
                    try:
                        await balance_crud.unblock_assets(order.user_id, order.ticker, remaining_qty, session)
                        error_log(f"Разблокировано активов: {remaining_qty} {order.ticker} для пользователя {order.user_id}")
                    except ValueError as e:
                        error_log(f"Ошибка при разблокировке активов: {str(e)}")
        
        await session.commit()
        return order

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

    @error_log
    async def get_orderbook(
        self,
        ticker: str,
        session: AsyncSession,
        limit: int = 100,
    ) -> dict:
        """
        Получение биржевого стакана для указанного тикера
        
        Args:
            ticker: тикер инструмента
            session: сессия БД
            limit: максимальное количество уровней в каждой стороне стакана
            
        Returns:
            Словарь с уровнями спроса (bid) и предложения (ask)
        """
        # Получаем активные заявки на покупку (bid)
        bids_query = select(Order.price, 
                            Order.qty, 
                            Order.filled).where(
            Order.ticker == ticker,
            Order.direction == OrderDirection.BUY,
            Order.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]),
            Order.price.isnot(None)  # Только лимитные заявки
        )
        
        bids_result = await session.execute(bids_query)
        bids_raw = bids_result.all()
        
        # Получаем активные заявки на продажу (ask)
        asks_query = select(Order.price, 
                           Order.qty, 
                           Order.filled).where(
            Order.ticker == ticker,
            Order.direction == OrderDirection.SELL,
            Order.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]),
            Order.price.isnot(None)  # Только лимитные заявки
        )
        
        asks_result = await session.execute(asks_query)
        asks_raw = asks_result.all()
        
        # Агрегируем заявки по ценовым уровням
        bid_levels = {}
        for price, qty, filled in bids_raw:
            remaining_qty = qty - (filled or 0)
            if remaining_qty <= 0:
                continue
                
            if price not in bid_levels:
                bid_levels[price] = 0
            bid_levels[price] += remaining_qty
            
        ask_levels = {}
        for price, qty, filled in asks_raw:
            remaining_qty = qty - (filled or 0)
            if remaining_qty <= 0:
                continue
                
            if price not in ask_levels:
                ask_levels[price] = 0
            ask_levels[price] += remaining_qty
            
        bids = [{"price": price, "qty": qty} 
                for price, qty in sorted(bid_levels.items(), key=lambda x: x[0], reverse=True)]
                
        asks = [{"price": price, "qty": qty} 
                for price, qty in sorted(ask_levels.items(), key=lambda x: x[0])]
        
        # Применяем лимит
        if limit:
            bids = bids[:limit]
            asks = asks[:limit]
            
        return {
            "bid_levels": bids,
            "ask_levels": asks
        }

order_crud = CRUDOrder()
