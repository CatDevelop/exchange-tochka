from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from app.core.logs.logs import error_log
from app.models.balance import Balance
from app.crud.v1.balance import balance_crud


async def deduct_funds(user_id: str, amount: int, ticker: str, session: AsyncSession):
    """Списание средств с баланса пользователя"""
    error_log(f"Списание средств: user_id={user_id}, ticker={ticker}, amount={amount}")
    await session.execute(
        Balance.__table__.update()
        .where(Balance.user_id == user_id, Balance.ticker == ticker)
        .values(amount=Balance.amount - amount)
    )


async def block_funds(user_id: str, amount: int, ticker: str, session: AsyncSession):
    """Блокировка денежных средств для лимитного ордера на покупку"""
    try:
        await balance_crud.block_funds(user_id, ticker, amount, session)
    except ValueError as e:
        # Логируем ошибку, но не прерываем выполнение
        error_log(f"Ошибка блокировки средств: {str(e)}")


async def block_assets(user_id: str, qty: int, ticker: str, session: AsyncSession):
    """Блокировка активов для лимитного ордера на продажу"""
    try:
        await balance_crud.block_assets(user_id, ticker, qty, session)
    except ValueError as e:
        # Логируем ошибку, но не прерываем выполнение
        error_log(f"Ошибка блокировки активов: {str(e)}")


async def refund_user(user_id: str, amount: int, ticker: str, session: AsyncSession):
    """Возврат средств на баланс пользователя"""
    error_log(f"Возврат средств: user_id={user_id}, ticker={ticker}, amount={amount}")
    await session.execute(
        Balance.__table__.update()
        .where(Balance.user_id == user_id, Balance.ticker == ticker)
        .values(amount=Balance.amount + amount)
    )


async def deduct_assets(user_id: str, qty: int, ticker: str, session: AsyncSession):
    """Списание активов с баланса пользователя"""
    error_log(f"Списание активов: user_id={user_id}, ticker={ticker}, qty={qty}")
    await session.execute(
        Balance.__table__.update()
        .where(Balance.user_id == user_id, Balance.ticker == ticker)
        .values(amount=Balance.amount - qty)
    )


async def add_assets(user_id: str, qty: int, ticker: str, session: AsyncSession):
    """Начисление активов на баланс пользователя"""
    error_log(f"Начисление активов: user_id={user_id}, ticker={ticker}, qty={qty}")
    # Проверяем, существует ли запись баланса
    result = await session.execute(
        select(Balance).where(
            Balance.user_id == user_id,
            Balance.ticker == ticker
        )
    )
    balance = result.scalars().first()
    
    if balance:
        # Если запись существует, обновляем её
        error_log(f"Обновление существующего баланса активов: было {balance.amount}, будет {balance.amount + qty}")
        await session.execute(
            Balance.__table__.update()
            .where(Balance.user_id == user_id, Balance.ticker == ticker)
            .values(amount=Balance.amount + qty)
        )
    else:
        # Если записи нет, создаём новую
        error_log(f"Создание нового баланса активов: {qty}")
        new_balance = Balance(user_id=user_id, ticker=ticker, amount=qty, blocked_amount=0)
        session.add(new_balance)


async def add_funds(user_id: str, amount: int, ticker: str, session: AsyncSession):
    """Начисление средств на баланс пользователя"""
    error_log(f"Начисление средств: user_id={user_id}, ticker={ticker}, amount={amount}")
    # Проверяем, существует ли запись баланса
    result = await session.execute(
        select(Balance).where(
            Balance.user_id == user_id,
            Balance.ticker == ticker
        )
    )
    balance = result.scalars().first()
    
    if balance:
        # Если запись существует, обновляем её
        error_log(f"Обновление существующего баланса средств: было {balance.amount}, будет {balance.amount + amount}")
        await session.execute(
            Balance.__table__.update()
            .where(Balance.user_id == user_id, Balance.ticker == ticker)
            .values(amount=Balance.amount + amount)
        )
    else:
        # Если записи нет, создаём новую
        error_log(f"Создание нового баланса средств: {amount}")
        new_balance = Balance(user_id=user_id, ticker=ticker, amount=amount, blocked_amount=0)
        session.add(new_balance) 