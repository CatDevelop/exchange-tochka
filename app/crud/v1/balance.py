from decimal import Decimal
from typing import Dict

from sqlalchemy import and_, select, update
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logs.logs import error_log
from app.crud.base import CRUDBase
from app.models.balance import Balance


class CRUDBalance(CRUDBase[Balance]):
    def __init__(self):
        super().__init__(Balance, primary_key_name='pk_balance')

    @error_log
    async def get_user_ticker_balance(
        self,
        user_id: str,
        ticker: str,
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
    async def get_user_available_balance(
        self,
        user_id: str,
        ticker: str,
        async_session: AsyncSession,
    ) -> int:
        """Получить доступный баланс пользователя (за вычетом заблокированных средств)"""
        result = await async_session.execute(
            select(self.model.amount, self.model.blocked_amount).where(
                and_(self.model.user_id == user_id, self.model.ticker == ticker)
            )
        )
        balance_row = result.first()
        if not balance_row:
            return 0
        
        amount, blocked_amount = balance_row
        return amount - blocked_amount

    @error_log
    async def get_user_balances(
        self,
        user_id: str,
        async_session: AsyncSession,
    ) -> Dict[str, int]:
        result = await async_session.execute(
            select(
                self.model.ticker, 
                self.model.amount, 
                self.model.blocked_amount
            ).where(
                self.model.user_id == user_id
            )
        )
        return {ticker: int(amount) for ticker, amount, blocked_amount in result.all()}

    @error_log
    async def deposit(
        self,
        user_id: str,
        ticker: str,
        amount: int,
        async_session: AsyncSession,
    ) -> Balance:
        error_log(f"Начало deposit: user_id={user_id}, ticker={ticker}, amount={amount}")
        if amount <= 0:
            error_log(f"Ошибка: сумма пополнения должна быть положительной")
            raise ValueError('Сумма пополнения должна быть положительной')

        try:
            error_log(f"Пытаемся обновить существующий баланс")
            result = await async_session.execute(
                update(self.model)
                .where(and_(self.model.user_id == user_id, self.model.ticker == ticker))
                .values(amount=self.model.amount + amount)
                .returning(self.model)
            )
            balance = result.scalar_one_or_none()

            if not balance:
                error_log(f"Баланс не найден, создаем новый")
                balance = self.model(user_id=user_id, ticker=ticker, amount=amount, blocked_amount=0)
                async_session.add(balance)
                await async_session.flush()
                error_log(f"Новый баланс создан")

            await async_session.commit()
            error_log(f"Транзакция завершена успешно")
            return balance

        except IntegrityError as e:
            error_log(f"IntegrityError: {str(e)}")
            await async_session.rollback()
            if 'positive_balance' in str(e):
                raise ValueError('Итоговый баланс не может быть отрицательным')
            raise ValueError('Ошибка при пополнении баланса')
        except DataError as e:
            error_log(f"DataError: {str(e)}")
            await async_session.rollback()
            raise ValueError('Некорректная сумма')
        except Exception as e:
            error_log(f"Неожиданная ошибка: {str(e)}")
            await async_session.rollback()
            raise ValueError(f'Ошибка при пополнении баланса: {str(e)}')

    @error_log
    async def withdraw(
        self,
        user_id: str,
        ticker: str,
        amount: int,
        async_session: AsyncSession | None = None,
    ) -> Balance:
        if amount <= 0:
            raise ValueError('Сумма списания должна быть положительной')

        try:
            # Проверяем доступный баланс (с учетом заблокированных средств)
            available_amount = await self.get_user_available_balance(user_id, ticker, async_session)
            if available_amount < amount:
                raise ValueError('Недостаточно доступных средств на балансе')

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

    @error_log
    async def block_funds(
        self,
        user_id: str,
        ticker: str,
        amount: int,
        async_session: AsyncSession,
    ) -> Balance:
        """Блокировка средств для ордера"""
        if amount <= 0:
            raise ValueError('Сумма блокировки должна быть положительной')

        try:
            # Строгий порядок блокировок: сначала RUB, потом тикер
            if ticker != "RUB":
                await async_session.execute(
                    select(self.model)
                    .where(and_(self.model.user_id == user_id, self.model.ticker == "RUB"))
                    .with_for_update()
                )
            # Проверяем доступный баланс
            available_amount = await self.get_user_available_balance(user_id, ticker, async_session)
            if available_amount < amount:
                raise ValueError('Недостаточно доступных средств для блокировки')

            result = await async_session.execute(
                update(self.model)
                .where(and_(self.model.user_id == user_id, self.model.ticker == ticker))
                .values(blocked_amount=self.model.blocked_amount + amount)
                .returning(self.model)
            )
            balance = result.scalar_one()

            await async_session.commit()
            return balance
        except IntegrityError as e:
            await async_session.rollback()
            if 'blocked_not_exceed_amount' in str(e):
                raise ValueError('Сумма блокировки не может превышать общий баланс')
            raise ValueError('Ошибка при блокировке средств')

    @error_log
    async def unblock_funds(
        self,
        user_id: str,
        ticker: str,
        amount: int,
        async_session: AsyncSession,
    ) -> Balance:
        """Разблокировка средств при отмене или исполнении ордера"""
        if amount <= 0:
            raise ValueError('Сумма разблокировки должна быть положительной')

        try:
            # Строгий порядок блокировок: сначала RUB, потом тикер
            if ticker != "RUB":
                await async_session.execute(
                    select(self.model)
                    .where(and_(self.model.user_id == user_id, self.model.ticker == "RUB"))
                    .with_for_update()
                )
            result = await async_session.execute(
                select(self.model)
                .where(
                    and_(self.model.user_id == user_id, self.model.ticker == ticker)
                )
                .with_for_update()
            )
            balance = result.scalar_one_or_none()
            
            if not balance or balance.blocked_amount < amount:
                raise ValueError('Недостаточно заблокированных средств для разблокировки')

            balance.blocked_amount -= amount
            await async_session.commit()
            
            return balance
        except IntegrityError:
            await async_session.rollback()
            raise ValueError('Ошибка при разблокировке средств')

    @error_log
    async def block_assets(
        self,
        user_id: str,
        ticker: str,
        qty: int,
        async_session: AsyncSession,
    ) -> Balance:
        """Блокировка активов для ордера на продажу"""
        return await self.block_funds(user_id, ticker, qty, async_session)

    @error_log
    async def unblock_assets(
        self,
        user_id: str,
        ticker: str,
        qty: int,
        async_session: AsyncSession,
    ) -> Balance:
        """Разблокировка активов при отмене или исполнении ордера на продажу"""
        return await self.unblock_funds(user_id, ticker, qty, async_session)


balance_crud = CRUDBalance()
