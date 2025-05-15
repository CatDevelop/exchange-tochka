from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logs.logs import error_log
from app.models import Order, Transaction
from app.models.order import OrderDirection, OrderStatus
from app.crud.v1.balance import balance_crud

from app.crud.v1.order.balance_operations import (
    lock_balance_row, 
    add_funds, 
    add_assets, 
    deduct_assets
)


async def match_sell_orders(ticker: str, qty: int, price: int | None, session: AsyncSession) -> dict:
    """Сопоставление заявок на продажу с заявкой на покупку"""
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
        await lock_balance_row(sell_order.user_id, "RUB", session)
        if ticker != "RUB":
            await lock_balance_row(sell_order.user_id, ticker, session)

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
        await add_funds(sell_order.user_id, order_cost, "RUB", session)
        
        # Разблокируем активы продавца, если это лимитная заявка
        if sell_order.price is not None:
            # Разблокировка активов
            try:
                await balance_crud.unblock_assets(sell_order.user_id, ticker, to_fill, session)
                error_log(f"Разблокировано активов: {to_fill} {ticker} для пользователя {sell_order.user_id}")
            except ValueError as e:
                error_log(f"Ошибка при разблокировке активов: {str(e)}")

        await create_transaction(
            user_id=sell_order.user_id,
            ticker=ticker,
            amount=to_fill,
            price=sell_order.price,
            session=session,
        )

        if filled_qty == qty:
            break

    return {"filled_qty": filled_qty, "spent_money": spent_money}


async def match_buy_orders(ticker: str, qty: int, price: int | None, session: AsyncSession) -> dict:
    """Сопоставление заявок на покупку с заявкой на продажу"""
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
        await lock_balance_row(buy_order.user_id, "RUB", session)
        if ticker != "RUB":
            await lock_balance_row(buy_order.user_id, ticker, session)

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
        await add_assets(buy_order.user_id, to_fill, ticker, session)
        
        # Разблокируем и списываем деньги у покупателя, если это лимитная заявка
        if buy_order.price is not None:
            # Разблокировка средств
            try:
                await balance_crud.unblock_funds(buy_order.user_id, "RUB", order_cost, session)
                error_log(f"Разблокировано средств: {order_cost} RUB для пользователя {buy_order.user_id}")
            except ValueError as e:
                error_log(f"Ошибка при разблокировке средств: {str(e)}")
        
        await create_transaction(
            user_id=buy_order.user_id,
            ticker=ticker,
            amount=to_fill,
            price=buy_order.price,
            session=session,
        )

        if filled_qty == qty:
            break

    return {"filled_qty": filled_qty, "earned_money": earned_money}


async def create_transaction(user_id: str, ticker: str, amount: int, price: int, session: AsyncSession):
    """Создание транзакции для записи в истории сделок"""
    transaction = Transaction(
        id=str(uuid4()),
        user_id=user_id,
        ticker=ticker,
        amount=amount,
        price=price,
        timestamp=datetime.utcnow(),
    )
    session.add(transaction) 