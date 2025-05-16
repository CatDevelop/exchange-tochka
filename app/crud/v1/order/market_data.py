from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logs.logs import error_log
from app.models import Order
from app.models.order import OrderDirection, OrderStatus


@error_log
async def get_orderbook(
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
    error_log(f"Формирование стакана для тикера {ticker}")
    
    # Получаем активные заявки на покупку (bid)
    bids_query = select(Order.price, 
                        Order.qty, 
                        Order.filled,
                        Order.id,
                        Order.status).where(
        Order.ticker == ticker,
        Order.direction == OrderDirection.BUY,
        Order.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]),
        Order.price.isnot(None),  # Только лимитные заявки
        Order.filled < Order.qty   # Только неполностью исполненные
    )
    
    bids_result = await session.execute(bids_query)
    bids_raw = bids_result.all()
    error_log(f"Найдено {len(bids_raw)} активных ордеров на покупку для тикера {ticker}")
    
    # Получаем активные заявки на продажу (ask)
    asks_query = select(Order.price, 
                       Order.qty, 
                       Order.filled,
                       Order.id,
                       Order.status).where(
        Order.ticker == ticker,
        Order.direction == OrderDirection.SELL,
        Order.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]),
        Order.price.isnot(None),  # Только лимитные заявки
        Order.filled < Order.qty   # Только неполностью исполненные
    )
    
    asks_result = await session.execute(asks_query)
    asks_raw = asks_result.all()
    error_log(f"Найдено {len(asks_raw)} активных ордеров на продажу для тикера {ticker}")
    
    # Агрегируем заявки по ценовым уровням
    bid_levels = {}
    for price, qty, filled, order_id, status in bids_raw:
        remaining_qty = qty - (filled or 0)
        if remaining_qty <= 0:
            error_log(f"Пропускаем ордер на покупку {order_id} со статусом {status}, т.к. неисполненная часть <= 0 (qty={qty}, filled={filled})")
            continue
            
        if price not in bid_levels:
            bid_levels[price] = 0
        bid_levels[price] += remaining_qty
        error_log(f"Добавляем в стакан ордер на покупку {order_id}: price={price}, qty={remaining_qty}")
        
    ask_levels = {}
    for price, qty, filled, order_id, status in asks_raw:
        remaining_qty = qty - (filled or 0)
        if remaining_qty <= 0:
            error_log(f"Пропускаем ордер на продажу {order_id} со статусом {status}, т.к. неисполненная часть <= 0 (qty={qty}, filled={filled})")
            continue
            
        if price not in ask_levels:
            ask_levels[price] = 0
        ask_levels[price] += remaining_qty
        error_log(f"Добавляем в стакан ордер на продажу {order_id}: price={price}, qty={remaining_qty}")
        
    bids = [{"price": price, "qty": qty} 
            for price, qty in sorted(bid_levels.items(), key=lambda x: x[0], reverse=True)]
            
    asks = [{"price": price, "qty": qty} 
            for price, qty in sorted(ask_levels.items(), key=lambda x: x[0])]
    
    # Применяем лимит
    if limit:
        bids = bids[:limit]
        asks = asks[:limit]
        
    error_log(f"Сформирован стакан для {ticker}: bid_levels={len(bids)}, ask_levels={len(asks)}")
    
    return {
        "bid_levels": bids,
        "ask_levels": asks
    } 