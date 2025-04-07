from decimal import Decimal
from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError, DataError
import uuid

from app.models.balance import Balance
from app.core.enums import CurrencyTicker
from app.crud.base import CRUDBase
from app.core.logs.logs import error_log


class CRUDBalance(CRUDBase[Balance]):
    @error_log
    async def get_user_balance(
        self,
        user_id: uuid.UUID,
        ticker: CurrencyTicker,
        async_session: AsyncSession | None = None,
    ) -> Decimal:
        """Получает баланс пользователя по тикеру валюты."""
        result = await async_session.execute(
            select(self.model.amount)
            .where(
                and_(
                    self.model.user_id == user_id,
                    self.model.ticker == ticker
                )
            )
        )
        balance = result.scalar_one_or_none()
        return balance or Decimal("0.0")

    @error_log
    async def deposit(
        self,
        user_id: uuid.UUID,
        ticker: CurrencyTicker,
        amount: Decimal,
        async_session: AsyncSession,
    ) -> Balance:
        """Пополняет баланс пользователя."""
        if amount <= Decimal('0'):
            raise ValueError("Сумма пополнения должна быть положительной")

        try:
            # Пытаемся обновить существующую запись
            result = await async_session.execute(
                update(self.model)
                .where(
                    and_(
                        self.model.user_id == user_id,
                        self.model.ticker == ticker
                    )
                )
                .values(amount=self.model.amount + amount)
                .returning(self.model)
            )
            balance = result.scalar_one_or_none()

            if not balance:
                # Если записи нет - создаем новую
                balance = self.model(
                    user_id=user_id,
                    ticker=ticker,
                    amount=amount
                )
                async_session.add(balance)
                await async_session.flush()

            await async_session.commit()
            return balance

        except IntegrityError as e:
            await async_session.rollback()
            if 'positive_balance' in str(e):
                raise ValueError("Итоговый баланс не может быть отрицательным")
            raise ValueError("Ошибка при пополнении баланса")
        except DataError:
            await async_session.rollback()
            raise ValueError("Некорректная сумма")

    @error_log
    async def withdraw(
        self,
        user_id: uuid.UUID,
        ticker: CurrencyTicker,
        amount: Decimal,
        async_session: AsyncSession | None = None,
    ) -> Balance:
        """Списывает средства с баланса пользователя."""
        if amount <= Decimal('0'):
            raise ValueError("Сумма списания должна быть положительной")

        try:
            # Проверяем достаточность средств
            current_balance = await self.get_user_balance(user_id, ticker, async_session)
            if current_balance < amount:
                raise ValueError("Недостаточно средств на балансе")

            # Выполняем списание
            result = await async_session.execute(
                update(self.model)
                .where(
                    and_(
                        self.model.user_id == user_id,
                        self.model.ticker == ticker
                    )
                )
                .values(amount=self.model.amount - amount)
                .returning(self.model)
            )
            balance = result.scalar_one()

            await async_session.commit()
            return balance

        except IntegrityError as e:
            await async_session.rollback()
            if 'positive_balance' in str(e):
                raise ValueError("Итоговый баланс не может быть отрицательным")
            raise ValueError("Ошибка при списании средств")
        except DataError:
            await async_session.rollback()
            raise ValueError("Некорректная сумма")


balance_crud = CRUDBalance(Balance)
