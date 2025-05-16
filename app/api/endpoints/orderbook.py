from typing import Optional

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_async_session
from app.crud.v1.order import order_crud
from app.crud.v1.transaction import transaction_crud
from app.schemas.order import OrderbookResponse
from app.schemas.transaction import TransactionResponse

router = APIRouter()


@router.get(
    '/public/orderbook/{ticker}',
    response_model=OrderbookResponse,
    summary='Получение стакана ордеров',
    tags=['public'],
)
async def get_orderbook(
        ticker: str = Path(..., description="Тикер иsнструмента"),
        limit: Optional[int] = Query(100, ge=1, le=1000, description="Максимальное количество уровней цен"),
        session: AsyncSession = Depends(get_async_session),
):
    """
    Получение текущего стакана ордеров (биржевой книги) для указанного тикера.
    
    - **ticker**: Тикер инструмента (например, BTC, ETH, USD)
    - **limit**: Максимальное количество уровней цен, которые будут возвращены
    
    Возвращает:
    - **bid_levels**: Уровни спроса (покупки), отсортированные по возрастанию цены
    - **ask_levels**: Уровни предложения (продажи), отсортированные по возрастанию цены
    """
    orderbook_data = await order_crud.get_orderbook(
        ticker=ticker,
        session=session,
        limit=limit
    )

    return OrderbookResponse(
        bid_levels=orderbook_data["bid_levels"],
        ask_levels=orderbook_data["ask_levels"]
    )


@router.get(
    '/transactions/{ticker}',
    response_model=list[TransactionResponse],
    summary='Получение истории транзакций',
    tags=['public'],
)
async def get_transaction_history(
        ticker: str = Path(..., description="Тикер инструмента"),
        limit: Optional[int] = Query(100, ge=1, le=1000, description="Максимальное количество транзакций"),
        session: AsyncSession = Depends(get_async_session),
):
    """
    Получение истории транзакций для указанного тикера.
    
    - **ticker**: Тикер инструмента (например, MEMECOIN, BTC, ETH)
    - **limit**: Максимальное количество транзакций, которые будут возвращены
    
    Возвращает список транзакций, отсортированных по времени (от новых к старым)
    """
    transactions = await transaction_crud.get_transactions_by_ticker(
        ticker=ticker,
        session=session,
        limit=limit
    )

    return transactions
