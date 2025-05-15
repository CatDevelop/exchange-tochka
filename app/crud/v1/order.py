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
                    await self._block_funds(user_id, (qty - filled) * price, "RUB", session)
                
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
                    await self._block_assets(user_id, qty - filled, ticker, session)
                
                status = (
                    OrderStatus.EXECUTED if filled == qty
                    else OrderStatus.PARTIALLY_EXECUTED if filled > 0
                    else OrderStatus.NEW
                )

        # Создаем запись в БД
        new_order = Order(
            id=order_id,
            status=status,
            user_id=user_id,
            direction=direction,
            ticker=ticker,
            qty=qty,
            price=price,
            filled=filled,
        )
        session.add(new_order)
        await session.commit()
        return new_order

    async def _match_sell_orders(self, ticker: str, qty: int, price: int | None, session: AsyncSession) -> dict:
        query = select(Order).where(
            Order.ticker == ticker,
            Order.direction == OrderDirection.SELL,
            Order.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]),
        ).order_by(Order.price.asc().nulls_last())

        if price is not None:
            query = query.where(Order.price <= price)

        result = await session.execute(query)
        sell_orders = result.scalars().all()

        filled_qty = 0
        spent_money = 0

        for sell_order in sell_orders:
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
        query = select(Order).where(
            Order.ticker == ticker,
            Order.direction == OrderDirection.BUY,
            Order.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]),
        ).order_by(Order.price.desc().nulls_last())

        if price is not None:
            query = query.where(Order.price >= price)

        result = await session.execute(query)
        buy_orders = result.scalars().all()

        filled_qty = 0
        earned_money = 0

        for buy_order in buy_orders:
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

order_crud = CRUDOrder()
