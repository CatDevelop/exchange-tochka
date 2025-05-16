from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logs.logs import error_log
from app.models import Order, Transaction
from app.models.order import OrderDirection, OrderStatus

from app.crud.v1.order.balance_operations import (
    add_funds, 
    add_assets, 
    deduct_assets,
    unblock_funds,
    unblock_assets
)


async def match_sell_orders(ticker: str, qty: int, price: int | None, session: AsyncSession) -> dict:
    """Сопоставление заявок на продажу с заявкой на покупку"""
    # Получаем подходящие ордера с блокировкой (FOR UPDATE SKIP LOCKED)
    query = select(Order).where(
        Order.ticker == ticker,
        Order.direction == OrderDirection.SELL,
        Order.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]),
        Order.qty > Order.filled,  # Только ордера с неисполненной частью
    ).order_by(Order.price.asc().nulls_last(), Order.id.asc())  # Сортировка по цене и ID для предотвращения deadlock

    if price is not None:
        query = query.where(Order.price <= price)

    # Используем FOR UPDATE SKIP LOCKED для избежания deadlock
    query = query.with_for_update(skip_locked=True)

    result = await session.execute(query)
    sell_orders = result.scalars().all()

    filled_qty = 0
    spent_money = 0
    executions = {}  # Словарь с информацией о выполненных ордерах
    
    error_log(f"Найдено {len(sell_orders)} ордеров на продажу для сопоставления")

    for sell_order in sell_orders:
        # Обрабатываем каждый ордер на продажу
        remaining = sell_order.qty - (sell_order.filled or 0)
        to_fill = min(qty - filled_qty, remaining)

        if to_fill <= 0:
            continue

        # Обновляем ордер на продажу
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
        
        # НЕ зачисляем деньги продавцу здесь, это делается в crud_order.py
        # await add_funds(sell_order.user_id, order_cost, "RUB", session)
        
        # Разблокируем активы продавца, если это лимитная заявка
        if sell_order.price is not None:
            try:
                await unblock_assets(sell_order.user_id, ticker, to_fill, session)
                error_log(f"Разблокировано активов: {to_fill} {ticker} для пользователя {sell_order.user_id}")
            except ValueError as e:
                error_log(f"Ошибка при разблокировке активов: {str(e)}")
                
        # НЕ списываем активы здесь, так как это делается в crud_order.py
        # await deduct_assets(sell_order.user_id, to_fill, ticker, session)
        # error_log(f"Списано активов: {to_fill} {ticker} у пользователя {sell_order.user_id}")

        # Создаем запись о транзакции
        transaction = Transaction(
            id=str(uuid4()),
            user_id=sell_order.user_id,
            ticker=ticker,
            amount=to_fill,
            price=sell_order.price,
            timestamp=datetime.utcnow(),
        )
        session.add(transaction)
        
        # Сохраняем информацию о выполнении для возврата
        executions[sell_order.id] = {
            "user_id": sell_order.user_id,
            "qty": to_fill,
            "price": order_price,
            "amount": order_cost
        }
        
        error_log(f"Сопоставлен ордер продажи {sell_order.id}: {to_fill} {ticker} по цене {order_price}, сумма {order_cost}")

        if filled_qty == qty:
            break
            
    error_log(f"Всего сопоставлено ордеров продажи: {len(executions)}, общее кол-во: {filled_qty}, общая сумма: {spent_money}")

    return {"filled_qty": filled_qty, "spent_money": spent_money, "executions": executions}


async def match_buy_orders(ticker: str, qty: int, price: int | None, session: AsyncSession) -> dict:
    """Сопоставление заявок на покупку с заявкой на продажу"""
    # Получаем подходящие ордера с блокировкой (FOR UPDATE SKIP LOCKED)
    query = select(Order).where(
        Order.ticker == ticker,
        Order.direction == OrderDirection.BUY,
        Order.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]),
        Order.qty > Order.filled,  # Только ордера с неисполненной частью
    ).order_by(Order.price.desc().nulls_last(), Order.id.asc())  # Сортировка по цене и ID для предотвращения deadlock

    if price is not None:
        query = query.where(Order.price >= price)

    # Используем FOR UPDATE SKIP LOCKED для избежания deadlock
    query = query.with_for_update(skip_locked=True)

    result = await session.execute(query)
    buy_orders = result.scalars().all()

    filled_qty = 0
    earned_money = 0
    executions = {}  # Словарь с информацией о выполненных ордерах
    
    error_log(f"Найдено {len(buy_orders)} ордеров на покупку для сопоставления")

    for buy_order in buy_orders:
        # Обрабатываем каждый ордер на покупку
        remaining = buy_order.qty - (buy_order.filled or 0)
        to_fill = min(qty - filled_qty, remaining)

        if to_fill <= 0:
            continue

        # Обновляем ордер на покупку
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
        
        # НЕ зачисляем актив покупателю здесь, это делается в crud_order.py
        # await add_assets(buy_order.user_id, to_fill, ticker, session)
        
        # Разблокируем и списываем деньги у покупателя, если это лимитная заявка
        if buy_order.price is not None:
            try:
                await unblock_funds(buy_order.user_id, "RUB", order_cost, session)
                error_log(f"Разблокировано средств: {order_cost} RUB для пользователя {buy_order.user_id}")
            except ValueError as e:
                error_log(f"Ошибка при разблокировке средств: {str(e)}")
        
        # Создаем запись о транзакции
        transaction = Transaction(
            id=str(uuid4()),
            user_id=buy_order.user_id,
            ticker=ticker,
            amount=to_fill,
            price=buy_order.price,
            timestamp=datetime.utcnow(),
        )
        session.add(transaction)
        
        # Сохраняем информацию о выполнении для возврата
        executions[buy_order.id] = {
            "user_id": buy_order.user_id,
            "qty": to_fill,
            "price": order_price,
            "amount": order_cost
        }
        
        error_log(f"Сопоставлен ордер покупки {buy_order.id}: {to_fill} {ticker} по цене {order_price}, сумма {order_cost}")

        if filled_qty == qty:
            break
            
    error_log(f"Всего сопоставлено ордеров покупки: {len(executions)}, общее кол-во: {filled_qty}, общая сумма: {earned_money}")

    return {"filled_qty": filled_qty, "earned_money": earned_money, "executions": executions} 