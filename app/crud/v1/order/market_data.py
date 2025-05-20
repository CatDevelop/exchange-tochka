from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logs.logs import error_log
from app.models import Order
from app.models.order import OrderDirection, OrderStatus, OrderBookLevels


@error_log
async def get_orderbook(
        ticker: str,
        session: AsyncSession,
        limit: int = 100,
        levels: OrderBookLevels = OrderBookLevels.ALL,
        user_id: str = None
) -> dict:
    """
    Получение биржевого стакана для указанного тикера

    Args:
        ticker: тикер инструмента
        session: сессия БД
        limit: максимальное количество уровней в каждой стороне стакана
        levels: какие типы заявок надо найти

    Returns:
        Словарь с уровнями спроса (bid) и предложения (ask)
    """

    bids = []
    asks = []

    if levels == OrderBookLevels.ALL or levels == OrderBookLevels.BID:
        bids_query = select(Order.price,
                            Order.qty,
                            Order.filled,
                            Order.id,
                            Order.status).where(
            Order.ticker == ticker,
            Order.direction == OrderDirection.BUY,
            Order.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]),
            Order.price.isnot(None),
            Order.filled < Order.qty,
            Order.user_id != user_id
        )

        bids_result = await session.execute(bids_query)
        bids_raw = bids_result.all()

        bid_levels = {}
        for price, qty, filled, order_id, status in bids_raw:
            remaining_qty = qty - (filled or 0)
            if remaining_qty <= 0:
                continue

            if price not in bid_levels:
                bid_levels[price] = 0
            bid_levels[price] += remaining_qty

        bids = [{"price": price, "qty": qty}
                for price, qty in sorted(bid_levels.items(), key=lambda x: x[0], reverse=True)]

    if levels == OrderBookLevels.ALL or levels == OrderBookLevels.ASK:
        # Получаем активные заявки на продажу (ask)
        asks_query = select(Order.price,
                            Order.qty,
                            Order.filled,
                            Order.id,
                            Order.status).where(
            Order.ticker == ticker,
            Order.direction == OrderDirection.SELL,
            Order.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]),
            Order.price.isnot(None),
            Order.filled < Order.qty,
            Order.user_id != user_id
        )

        asks_result = await session.execute(asks_query)
        asks_raw = asks_result.all()

        ask_levels = {}
        for price, qty, filled, order_id, status in asks_raw:
            remaining_qty = qty - (filled or 0)
            if remaining_qty <= 0:
                continue

            if price not in ask_levels:
                ask_levels[price] = 0
            ask_levels[price] += remaining_qty

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
