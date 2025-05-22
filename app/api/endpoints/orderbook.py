from typing import Optional

from fastapi import APIRouter, Depends, Path, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_async_session
from app.core.logs.logs import info_logger
from app.crud.v1.order import order_crud
from app.crud.v1.transaction import transaction_crud
from app.models.order import OrderBookLevels
from app.schemas.order import OrderbookResponse
from app.schemas.transaction import TransactionResponse

router = APIRouter()


@router.get(
    '/public/orderbook/{ticker}',
    response_model=OrderbookResponse,
    summary='Get Orderbook',
    tags=['public'],
)
async def get_orderbook(
    ticker: str = Path(..., description='Тикер инструмента'),
    limit: Optional[int] = Query(
        10, ge=1, le=25, description='Максимальное количество уровней цен'
    ),
    session: AsyncSession = Depends(get_async_session),
):
    try:
        orderbook_data = await order_crud.get_orderbook(
            ticker=ticker, session=session, limit=limit, levels=OrderBookLevels.ALL
        )
        info_logger.info(orderbook_data)

        return OrderbookResponse(
            bid_levels=orderbook_data['bid_levels'], ask_levels=orderbook_data['ask_levels']
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера get_orderbook: {str(e)}")

@router.get(
    '/public/transactions/{ticker}',
    response_model=list[TransactionResponse],
    summary='Получение истории транзакций',
    tags=['public'],
)
async def get_transaction_history(
    ticker: str = Path(..., description='Тикер инструмента'),
    limit: Optional[int] = Query(
        10, ge=1, le=100, description='Максимальное количество транзакций'
    ),
    session: AsyncSession = Depends(get_async_session),
):
    try:
        transactions = await transaction_crud.get_transactions_by_ticker(
            ticker=ticker, session=session, limit=limit
        )

        return transactions
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера get_transaction_history: {str(e)}")
