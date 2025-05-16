from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logs.logs import error_log
from app.crud.base import CRUDBase
from app.models.transaction import Transaction


class CRUDTransaction(CRUDBase[Transaction]):
    def __init__(self):
        super().__init__(Transaction, primary_key_name='id')

    @error_log
    async def get_transactions_by_ticker(
            self,
            ticker: str,
            session: AsyncSession,
            limit: int = 100,
    ) -> list[Transaction]:
        """Получение списка транзакций по тикеру"""

        query = select(Transaction).where(
            Transaction.ticker == ticker
        ).order_by(
            Transaction.timestamp.desc()
        ).limit(limit)

        result = await session.execute(query)
        transactions = result.scalars().all()

        # Добавляем информацию о временной зоне к каждой транзакции
        for transaction in transactions:
            if transaction.timestamp and transaction.timestamp.tzinfo is None:
                transaction.timestamp = transaction.timestamp.replace(tzinfo=timezone.utc)

        return transactions


transaction_crud = CRUDTransaction()
