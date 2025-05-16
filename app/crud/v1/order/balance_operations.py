import zlib
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from app.core.logs.logs import error_log
from app.models.balance import Balance
from app.crud.v1.balance import balance_crud


async def get_global_lock(user_id: str, session: AsyncSession):
    """Получение глобальной advisory lock для всех операций пользователя"""
    key = zlib.crc32(f"{user_id}:GLOBAL".encode()) % 2_147_483_647
    await session.execute(text(f"SELECT pg_advisory_xact_lock({key})"))
    error_log(f"Получена глобальная advisory lock для user_id={user_id}, key={key}")


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
    error_log(f"Блокировка средств: user_id={user_id}, ticker={ticker}, amount={amount}")
    
    # Получаем баланс с блокировкой строки
    result = await session.execute(
        select(Balance).where(
            Balance.user_id == user_id,
            Balance.ticker == ticker
        ).with_for_update()
    )
    balance = result.scalar_one_or_none()
    
    if not balance:
        error_msg = f"Баланс {ticker} не найден для пользователя {user_id}"
        error_log(error_msg)
        raise ValueError(error_msg)
    
    if balance.amount - balance.blocked_amount < amount:
        error_msg = f"Недостаточно средств для блокировки. Требуется: {amount}, доступно: {balance.amount - balance.blocked_amount}"
        error_log(error_msg)
        raise ValueError(error_msg)
    
    # Блокируем средства
    balance.blocked_amount += amount
    error_log(f"Средства заблокированы: {amount} {ticker}, новый заблокированный баланс: {balance.blocked_amount}")


async def block_assets(user_id: str, qty: int, ticker: str, session: AsyncSession):
    """Блокировка активов для лимитного ордера на продажу"""
    error_log(f"Блокировка активов: user_id={user_id}, ticker={ticker}, qty={qty}")
    
    # Получаем баланс с блокировкой строки
    result = await session.execute(
        select(Balance).where(
            Balance.user_id == user_id,
            Balance.ticker == ticker
        ).with_for_update()
    )
    balance = result.scalar_one_or_none()
    
    if not balance:
        error_msg = f"Баланс {ticker} не найден для пользователя {user_id}"
        error_log(error_msg)
        raise ValueError(error_msg)
    
    if balance.amount - balance.blocked_amount < qty:
        error_msg = f"Недостаточно активов для блокировки. Требуется: {qty}, доступно: {balance.amount - balance.blocked_amount}"
        error_log(error_msg)
        raise ValueError(error_msg)
    
    # Блокируем активы
    balance.blocked_amount += qty
    error_log(f"Активы заблокированы: {qty} {ticker}, новый заблокированный баланс: {balance.blocked_amount}")


async def unblock_funds(user_id: str, ticker: str, amount: int, session: AsyncSession):
    """Разблокировка денежных средств"""
    error_log(f"Разблокировка средств: user_id={user_id}, ticker={ticker}, amount={amount}")
    
    # Получаем баланс с блокировкой строки
    result = await session.execute(
        select(Balance).where(
            Balance.user_id == user_id,
            Balance.ticker == ticker
        ).with_for_update()
    )
    balance = result.scalar_one_or_none()
    
    if not balance:
        error_msg = f"Баланс {ticker} не найден для пользователя {user_id}"
        error_log(error_msg)
        raise ValueError(error_msg)
    
    # Не разблокируем больше, чем заблокировано
    actual_unblock = min(amount, balance.blocked_amount)
    
    if actual_unblock > 0:
        balance.blocked_amount -= actual_unblock
        error_log(f"Средства разблокированы: {actual_unblock} {ticker} из запрошенных {amount}, оставшийся заблокированный баланс: {balance.blocked_amount}")
    else:
        error_log(f"Нечего разблокировать: запрошено {amount}, заблокировано {balance.blocked_amount}")


async def unblock_assets(user_id: str, ticker: str, qty: int, session: AsyncSession):
    """Разблокировка активов"""
    error_log(f"Разблокировка активов: user_id={user_id}, ticker={ticker}, qty={qty}")
    
    # Получаем баланс с блокировкой строки
    result = await session.execute(
        select(Balance).where(
            Balance.user_id == user_id,
            Balance.ticker == ticker
        ).with_for_update()
    )
    balance = result.scalar_one_or_none()
    
    if not balance:
        error_msg = f"Баланс {ticker} не найден для пользователя {user_id}"
        error_log(error_msg)
        raise ValueError(error_msg)
    
    # Не разблокируем больше, чем заблокировано
    actual_unblock = min(qty, balance.blocked_amount)
    
    if actual_unblock > 0:
        balance.blocked_amount -= actual_unblock
        error_log(f"Активы разблокированы: {actual_unblock} {ticker} из запрошенных {qty}, оставшийся заблокированный баланс: {balance.blocked_amount}")
    else:
        error_log(f"Нечего разблокировать: запрошено {qty}, заблокировано {balance.blocked_amount}")


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
    
    # Проверяем текущий баланс для логирования
    result = await session.execute(
        select(Balance).where(
            Balance.user_id == user_id,
            Balance.ticker == ticker
        )
    )
    balance = result.scalars().first()
    
    if balance:
        error_log(f"Текущий баланс перед списанием: {balance.amount} {ticker}, заблокировано: {balance.blocked_amount}")
    else:
        error_log(f"Баланс {ticker} не найден для пользователя {user_id}")
    
    await session.execute(
        Balance.__table__.update()
        .where(Balance.user_id == user_id, Balance.ticker == ticker)
        .values(amount=Balance.amount - qty)
    )
    
    # Проверяем обновленный баланс для логирования
    result = await session.execute(
        select(Balance).where(
            Balance.user_id == user_id,
            Balance.ticker == ticker
        )
    )
    updated_balance = result.scalars().first()
    
    if updated_balance:
        error_log(f"Обновленный баланс после списания: {updated_balance.amount} {ticker}, заблокировано: {updated_balance.blocked_amount}")
    else:
        error_log(f"Обновленный баланс не найден (странно!)")


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