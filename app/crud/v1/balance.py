from decimal import Decimal
from typing import Dict

from sqlalchemy import and_, select, update
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import CurrencyTicker
from app.core.logs.logs import error_log
from app.crud.base import CRUDBase
from app.models.balance import Balance


class CRUDBalance(CRUDBase[Balance]):
    @error_log
    async def get_user_ticker_balance(
        self,
        user_id: int,
        ticker: CurrencyTicker,
        async_session: AsyncSession | None = None,
    ) -> Decimal:
        result = await async_session.execute(
            select(self.model.amount).where(
                and_(self.model.user_id == user_id, self.model.ticker == ticker)
            )
        )
        balance = result.scalar_one_or_none()
        return balance or Decimal('0.0')

    @error_log
    async def get_user_balances(
        self,
        user_id: int,
        async_session: AsyncSession,
    ) -> Dict[str, int]:
        result = await async_session.execute(
            select(self.model.ticker, self.model.amount).where(
                self.model.user_id == user_id
            )
        )
        return {ticker: int(amount) for ticker, amount in result.all()}

    @error_log
    async def deposit(
        self,
        user_id: int,
        ticker: CurrencyTicker,
        amount: Decimal,
        async_session: AsyncSession,
    ) -> Balance:
        if amount <= Decimal('0'):
            raise ValueError('Сумма пополнения должна быть положительной')

        try:
            result = await async_session.execute(
                update(self.model)
                .where(and_(self.model.user_id == user_id, self.model.ticker == ticker))
                .values(amount=self.model.amount + amount)
                .returning(self.model)
            )
            balance = result.scalar_one_or_none()

            if not balance:
                balance = self.model(user_id=user_id, ticker=ticker, amount=amount)
                async_session.add(balance)
                await async_session.flush()

            await async_session.commit()
            return balance

        except IntegrityError as e:
            await async_session.rollback()
            if 'positive_balance' in str(e):
                raise ValueError('Итоговый баланс не может быть отрицательным')
            raise ValueError('Ошибка при пополнении баланса')
        except DataError:
            await async_session.rollback()
            raise ValueError('Некорректная сумма')

    @error_log
    async def withdraw(
        self,
        user_id: int,
        ticker: CurrencyTicker,
        amount: Decimal,
        async_session: AsyncSession | None = None,
    ) -> Balance:
        if amount <= Decimal('0'):
            raise ValueError('Сумма списания должна быть положительной')

        try:
            current_balance = await self.get_user_ticker_balance(
                user_id, ticker, async_session
            )
            if current_balance < amount:
                raise ValueError('Недостаточно средств на балансе')

            result = await async_session.execute(
                update(self.model)
                .where(and_(self.model.user_id == user_id, self.model.ticker == ticker))
                .values(amount=self.model.amount - amount)
                .returning(self.model)
            )
            balance = result.scalar_one()

            await async_session.commit()
            return balance

        except IntegrityError as e:
            await async_session.rollback()
            if 'positive_balance' in str(e):
                raise ValueError('Итоговый баланс не может быть отрицательным')
            raise ValueError('Ошибка при списании средств')
        except DataError:
            await async_session.rollback()
            raise ValueError('Некорректная сумма')


balance_crud = CRUDBalance(Balance)
