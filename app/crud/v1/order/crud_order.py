import time
from uuid import uuid4
import zlib

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logs.logs import error_log
from app.models import Order, Balance
from app.models.order import OrderDirection, OrderStatus
from app.schemas.order import LimitOrderBody, MarketOrderBody
from app.crud.v1.balance import balance_crud

from app.crud.v1.order.base import CRUDOrderBase
from app.crud.v1.order.balance_operations import (
    block_funds, 
    block_assets, 
    add_assets,
    add_funds,
    deduct_funds,
    deduct_assets,
    get_global_lock,
    unblock_funds,
    unblock_assets
)
from app.crud.v1.order.matching_engine import match_sell_orders, match_buy_orders
from app.crud.v1.order.market_data import get_orderbook


class InsufficientFundsError(ValueError):
    """Ошибка недостаточного баланса с созданным CANCELLED ордером"""
    def __init__(self, message: str, order: Order):
        super().__init__(message)
        self.order = order


class CRUDOrder(CRUDOrderBase):
    """Класс для работы с ордерами"""

    @error_log
    async def _check_balance_availability(
        self, 
        user_id: str, 
        direction: OrderDirection, 
        ticker: str, 
        qty: int, 
        price: int | None, 
        session: AsyncSession
    ) -> None:
        """Проверка достаточности баланса без блокировки строк"""
        is_limit = price is not None
        
        if direction == OrderDirection.BUY:
            # Проверяем наличие RUB баланса
            rub_check = await session.execute(
                select(Balance).where(
                    Balance.user_id == user_id, 
                    Balance.ticker == "RUB"
                )
            )
            rub_balance_check = rub_check.scalar_one_or_none()
            
            if is_limit:
                # Для лимитных ордеров проверяем точное соответствие требуемой суммы
                if not rub_balance_check or rub_balance_check.amount - rub_balance_check.blocked_amount < qty * price:
                    available = rub_balance_check.amount - rub_balance_check.blocked_amount if rub_balance_check else 0
                    required = qty * price
                    error_msg = f"Недостаточно средств для создания ордера на покупку. Требуется: {required} RUB, доступно: {available} RUB"
                    error_log(error_msg)
                    raise ValueError(error_msg)
            else:
                # Для рыночных ордеров проверяем наличие хотя бы положительного баланса
                if not rub_balance_check or rub_balance_check.amount - rub_balance_check.blocked_amount <= 0:
                    available = rub_balance_check.amount - rub_balance_check.blocked_amount if rub_balance_check else 0
                    error_msg = f"Недостаточно средств для создания рыночного ордера на покупку. Доступно: {available} RUB"
                    error_log(error_msg)
                    raise ValueError(error_msg)
        
        elif direction == OrderDirection.SELL:
            # Проверяем наличие достаточного количества актива для продажи
            asset_check = await session.execute(
                select(Balance).where(
                    Balance.user_id == user_id, 
                    Balance.ticker == ticker
                )
            )
            asset_balance_check = asset_check.scalar_one_or_none()
            
            if not asset_balance_check or asset_balance_check.amount - asset_balance_check.blocked_amount < qty:
                available = asset_balance_check.amount - asset_balance_check.blocked_amount if asset_balance_check else 0
                error_msg = f"Недостаточно средств для создания ордера на продажу. Требуется: {qty} {ticker}, доступно: {available} {ticker}"
                error_log(error_msg)
                raise ValueError(error_msg)

    @error_log
    async def create_order(
            self,
            user_id: str,
            body: LimitOrderBody | MarketOrderBody,
            session: AsyncSession,
    ) -> Order:
        """Создание нового ордера с учетом сопоставления с существующими ордерами"""
        try:
            # Получаем глобальную блокировку для всех операций пользователя
            await get_global_lock(user_id, session)
            error_log(f"Получена глобальная блокировка для пользователя {user_id}")
            
            # Инициализируем параметры ордера
            order_id = str(uuid4())
            price = getattr(body, 'price', None)
            is_limit = price is not None
            direction = body.direction
            ticker = body.ticker
            qty = body.qty
        
            filled = 0
            spent_money = 0
            earned_money = 0
            
            # Проверка достаточности баланса без блокировки
            await self._check_balance_availability(user_id, direction, ticker, qty, price, session)
            
            # Сначала создаем запись ордера, затем блокируем балансы
            # Это устанавливает единый порядок блокировок: сначала Order, потом Balance
            order = Order(
                id=order_id,
                status=OrderStatus.NEW,
                user_id=user_id,
                direction=direction,
                ticker=ticker,
                qty=qty,
                price=price,
                filled=0,
            )
            session.add(order)
            await session.flush()  # Фиксируем в БД, но без коммита
            error_log(f"Создан новый ордер {order_id}")
            
            # Блокируем балансы после создания ордера
            if direction == OrderDirection.BUY and is_limit:
                # Блокируем средства для лимитного ордера на покупку
                await block_funds(user_id, qty * price, "RUB", session)
            elif direction == OrderDirection.SELL:
                # Блокируем активы для ордера на продажу
                await block_assets(user_id, qty, ticker, session)
            
            # Сопоставление с существующими ордерами
            rub_balance = None
            asset_balance = None
            
            # Получаем записи баланса с блокировкой для дальнейших операций
            if direction == OrderDirection.BUY or ticker == "RUB":
                rub_result = await session.execute(
                    select(Balance).where(
                        Balance.user_id == user_id, 
                        Balance.ticker == "RUB"
                    ).with_for_update()
                )
                rub_balance = rub_result.scalar_one_or_none()
            
            if direction == OrderDirection.SELL or ticker != "RUB":
                asset_result = await session.execute(
                    select(Balance).where(
                        Balance.user_id == user_id, 
                        Balance.ticker == ticker
                    ).with_for_update()
                )
                asset_balance = asset_result.scalar_one_or_none()
            
            # Сопоставление ордеров
            if direction == OrderDirection.BUY:
                filled, spent_money = await self._process_buy_matching(
                    user_id, ticker, qty, price, rub_balance, asset_balance, session
                )
                
                # Проверка результатов матчинга для рыночных ордеров на покупку
                if not is_limit and filled == 0:
                    error_log(f"Рыночный ордер на покупку {order_id} не выполнен из-за отсутствия подходящих предложений или недостаточного баланса")
                    order.status = OrderStatus.CANCELLED
                
            elif direction == OrderDirection.SELL:
                filled, earned_money = await self._process_sell_matching(
                    user_id, ticker, qty, price, rub_balance, asset_balance, session
                )
                
                # Проверка результатов матчинга для рыночных ордеров на продажу
                if not is_limit and filled == 0:
                    error_log(f"Рыночный ордер на продажу {order_id} не выполнен из-за отсутствия подходящих предложений")
                    order.status = OrderStatus.CANCELLED
            
            # Установка статуса ордера (если он не был установлен напрямую выше)
            if order.status != OrderStatus.CANCELLED:
                await self._set_order_status(order, is_limit, filled, qty)
            
            # Обновляем количество исполненных единиц ордера
            order.filled = filled
            
            # Делаем коммит транзакции
            await session.commit()
            return order
                
        except Exception as e:
            # Логируем ошибку
            error_log(f"Ошибка при создании ордера: {str(e)}")
            
            # Откатываем транзакцию
            try:
                await session.rollback()
            except Exception as rollback_error:
                error_log(f"Ошибка при откате транзакции: {str(rollback_error)}")
            
            # Выбрасываем исключение дальше
            raise ValueError(f"Ошибка при создании ордера: {str(e)}")

    @error_log
    async def _lock_balances(
        self, 
        user_id: str, 
        direction: OrderDirection, 
        ticker: str, 
        qty: int, 
        price: int | None, 
        session: AsyncSession
    ) -> tuple:
        """Блокировка строк баланса и проверка достаточности средств после блокировки"""
        is_limit = price is not None
        
        # Фиксированный порядок получения блокировок для предотвращения deadlock
        # Всегда сначала блокируем RUB, потом ticker
        
        # Получаем advisory lock для предотвращения рейсов в рамках транзакции
        # Используем разные хеши для разных пользователей и тикеров
        rub_hash = zlib.crc32(f"{user_id}:RUB".encode()) % 2147483647
        ticker_hash = zlib.crc32(f"{user_id}:{ticker}".encode()) % 2147483647
        
        # Получаем адвизори блокировки в фиксированном порядке - сначала для RUB, потом для ticker
        await session.execute(text(f"SELECT pg_advisory_xact_lock({rub_hash})"))
        error_log(f"Получена advisory lock для user_id={user_id}, ticker=RUB, hash={rub_hash}")
        
        if ticker != "RUB":  # Избегаем двойной блокировки, если ticker == "RUB"
            await session.execute(text(f"SELECT pg_advisory_xact_lock({ticker_hash})"))
            error_log(f"Получена advisory lock для user_id={user_id}, ticker={ticker}, hash={ticker_hash}")
        
        # Блокируем строки баланса в фиксированном порядке - сначала RUB, потом ticker
        rub_balance = await session.execute(
            select(Balance).where(
                Balance.user_id == user_id, 
                Balance.ticker == "RUB"
            ).with_for_update()
        )
        rub_balance = rub_balance.scalar_one_or_none()
        
        # Блокируем строку баланса тикера только если это не RUB (который уже заблокирован)
        if ticker != "RUB":
            asset_balance = await session.execute(
                select(Balance).where(
                    Balance.user_id == user_id, 
                    Balance.ticker == ticker
                ).with_for_update()
            )
            asset_balance = asset_balance.scalar_one_or_none()
        else:
            # Если ticker == "RUB", то используем тот же объект баланса
            asset_balance = rub_balance
            
        # Проверяем достаточность средств в зависимости от направления операции
        if direction == OrderDirection.BUY:
            # Проверка для ордера на покупку
            if is_limit:  # Лимитный ордер на покупку
                if not rub_balance or rub_balance.amount - rub_balance.blocked_amount < qty * price:
                    available = rub_balance.amount - rub_balance.blocked_amount if rub_balance else 0
                    required = qty * price
                    error_msg = f"Недостаточно средств для создания ордера на покупку. Требуется: {required} RUB, доступно: {available} RUB"
                    error_log(error_msg)
                    raise ValueError(error_msg)
                
                # Блокируем средства для лимитного ордера на покупку
                rub_balance.blocked_amount += qty * price
                error_log(f"Заблокировано {qty * price} RUB для покупки {qty} {ticker}")
        
        elif direction == OrderDirection.SELL:
            # Проверка для ордера на продажу
            if not asset_balance or asset_balance.amount - asset_balance.blocked_amount < qty:
                available = asset_balance.amount - asset_balance.blocked_amount if asset_balance else 0
                error_msg = f"Недостаточно средств для создания ордера на продажу. Требуется: {qty} {ticker}, доступно: {available} {ticker}"
                error_log(error_msg)
                raise ValueError(error_msg)
            
            # Блокируем активы для продажи (для лимитных и рыночных ордеров)
            asset_balance.blocked_amount += qty
            error_log(f"Заблокировано {qty} {ticker} для продажи")
            
        return rub_balance, asset_balance

    @error_log
    async def _unblock_funds_for_cancelled_order(
        self,
        order: Order,
        session: AsyncSession,
    ) -> None:
        """Разблокировка средств при отмене или полном исполнении заявки"""
        # Рассчитываем неисполненную часть ордера
        remaining_qty = order.qty - (order.filled or 0)
        
        # Логируем информацию о разблокируемых средствах
        error_log(f"Разблокировка средств для ордера {order.id}: статус={order.status}, "
                  f"направление={order.direction}, всего={order.qty}, исполнено={order.filled}, "
                  f"осталось={remaining_qty}")
        
        if remaining_qty <= 0:
            error_log(f"Нет неисполненной части для разблокировки в ордере {order.id}")
            return
        
        if order.direction == OrderDirection.BUY:
            # Разблокируем деньги у покупателя только для лимитных ордеров
            # Для рыночных ордеров price будет None
            if order.price is not None:
                remaining_cost = remaining_qty * order.price
                try:
                    await unblock_funds(order.user_id, "RUB", remaining_cost, session)
                    error_log(f"Разблокировано средств: {remaining_cost} RUB для пользователя {order.user_id}")
                except ValueError as e:
                    error_log(f"Ошибка при разблокировке средств: {str(e)}")
        
        elif order.direction == OrderDirection.SELL:
            # Разблокируем активы у продавца только для лимитных ордеров
            # Для рыночных ордеров нет заблокированных активов
            if order.price is not None:
                try:
                    await unblock_assets(order.user_id, order.ticker, remaining_qty, session)
                    error_log(f"Разблокировано активов: {remaining_qty} {order.ticker} для пользователя {order.user_id}")
                except ValueError as e:
                    error_log(f"Ошибка при разблокировке активов: {str(e)}")

    @error_log
    async def update_order_status(
        self,
        order_id: str,
        new_status: OrderStatus,
        session: AsyncSession,
    ) -> Order:
        """Обновление статуса заявки с разблокировкой средств при необходимости"""
        try:
            # Получаем ордер с блокировкой
            result = await session.execute(
                select(Order).where(Order.id == order_id).with_for_update()
            )
            order = result.scalar_one_or_none()
            
            # Если ордер не существует
            if not order:
                raise ValueError(f"Заявка с ID {order_id} не найдена")
            
            # Получаем глобальную блокировку для всех операций пользователя
            await get_global_lock(order.user_id, session)
            error_log(f"Получена глобальная блокировка для пользователя {order.user_id} при обновлении статуса заявки")
            
            # Проверяем, полностью ли исполнен ордер
            is_fully_executed = order.filled is not None and order.filled >= order.qty
            
            # Если ордер полностью исполнен, но его статус не EXECUTED, устанавливаем статус EXECUTED
            if is_fully_executed and order.status != OrderStatus.EXECUTED:
                error_log(f"Ордер {order_id} полностью исполнен (filled={order.filled}, qty={order.qty}), устанавливаем статус EXECUTED")
                order.status = OrderStatus.EXECUTED
                await session.commit()
                return order
            
            # Если статус не изменился, просто возвращаем заявку
            if order.status == new_status:
                return order
            
            # Если заявка уже отменена или исполнена, не позволяем менять статус
            if order.status in [OrderStatus.CANCELLED, OrderStatus.EXECUTED]:
                raise ValueError(f"Нельзя изменить статус заявки в статусе {order.status}")
            
            # Проверяем, остались ли неисполненные единицы в ордере
            remaining_qty = order.qty - (order.filled or 0)
            if remaining_qty <= 0 and new_status == OrderStatus.CANCELLED:
                # Если ордер полностью исполнен, нельзя его отменить
                raise ValueError(f"Нельзя отменить полностью исполненный ордер. Заполнено: {order.filled} из {order.qty}")
            
            # Меняем статус заявки
            old_status = order.status
            order.status = new_status
            
            # Логируем изменение статуса
            error_log(f"Изменен статус ордера {order_id} с {old_status} на {new_status}. Заполнено: {order.filled} из {order.qty}")
            
            # Если заявка отменяется или исполняется полностью, разблокируем средства
            if new_status in [OrderStatus.CANCELLED, OrderStatus.EXECUTED]:
                await self._unblock_funds_for_cancelled_order(order, session)
        
            # Делаем коммит внешней транзакции
            await session.commit()
            return order
                
        except Exception as e:
            # Логируем ошибку
            error_log(f"Ошибка при обновлении статуса ордера: {str(e)}")
            
            # Откатываем транзакцию
            try:
                await session.rollback()
            except Exception as rollback_error:
                error_log(f"Ошибка при откате транзакции: {str(rollback_error)}")
            
            # Выбрасываем исключение дальше
            raise ValueError(f"Ошибка при обновлении статуса ордера: {str(e)}")
            
    @error_log
    async def _process_buy_matching(
        self, 
        user_id: str,
        ticker: str, 
        qty: int, 
        price: int | None, 
        rub_balance: Balance, 
        asset_balance: Balance, 
        session: AsyncSession
    ) -> tuple:
        """Обработка сопоставления ордера на покупку с существующими ордерами на продажу"""
        is_limit = price is not None
        
        # Для рыночных ордеров проверяем, есть ли вообще предложения на продажу
        if not is_limit:
            # Проверяем наличие ордеров на продажу для данного тикера
            sell_count = await session.execute(
                select(func.count()).where(
                    Order.ticker == ticker,
                    Order.direction == OrderDirection.SELL,
                    Order.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED])
                )
            )
            sell_count = sell_count.scalar_one()
            
            if sell_count == 0:
                error_log(f"Нет активных ордеров на продажу для тикера {ticker}. Рыночный ордер на покупку отменен.")
                return 0, 0
        
        matched_orders = await match_sell_orders(ticker, qty, price, session)
        filled = matched_orders["filled_qty"]
        spent_money = matched_orders["spent_money"]
        
        # Для рыночных ордеров проверяем достаточность средств после получения стоимости
        if not is_limit and filled > 0:
            if not rub_balance or rub_balance.amount < spent_money:
                available = rub_balance.amount if rub_balance else 0
                error_msg = f"Недостаточно средств для исполнения рыночного ордера на покупку. Требуется: {spent_money} RUB, доступно: {available} RUB"
                error_log(error_msg)
                # Создаем CANCELLED ордер, так как не хватает средств
                return 0, 0  # Возвращаем 0, 0, чтобы ордер был помечен как CANCELLED
        
        if filled > 0:
            # Обновляем балансы для каждого продавца, с которым был матчинг
            for seller_order_id, execution_info in matched_orders.get("executions", {}).items():
                await self._update_seller_balance_buy_match(
                    execution_info["user_id"],
                    ticker,
                    execution_info["qty"],
                    execution_info["price"],
                    session
                )
            
            # Обновляем баланс покупателя
            if is_limit:
                # Разблокируем потраченные средства для лимитного ордера
                rub_balance.blocked_amount -= min(spent_money, rub_balance.blocked_amount)
            
            # Убедимся, что не уйдем в отрицательный баланс для рыночных ордеров
            if rub_balance.amount < spent_money:
                error_log(f"Попытка списать {spent_money} RUB при доступном балансе {rub_balance.amount} RUB - ограничиваем списание")
                spent_money = rub_balance.amount
                
            rub_balance.amount -= spent_money  # Списываем потраченные средства
            
            if asset_balance:
                asset_balance.amount += filled  # Добавляем купленные активы
            else:
                # Создаем новый баланс активов
                new_asset_balance = Balance(
                    user_id=user_id,
                    ticker=ticker,
                    amount=filled,
                    blocked_amount=0
                )
                session.add(new_asset_balance)
        
        # Если это рыночная заявка или полностью исполненная лимитная
        if is_limit and (filled == qty or not is_limit):
            # Если осталась блокировка, разблокируем лишнее (только для лимитных ордеров)
            if rub_balance.blocked_amount > 0 and filled < qty:
                remaining_block = qty * price - spent_money
                # Не разблокируем больше, чем есть в blocked_amount
                actual_unblock = min(remaining_block, rub_balance.blocked_amount)
                rub_balance.blocked_amount -= actual_unblock
                error_log(f"Разблокировано {actual_unblock} RUB после исполнения/отмены ордера")
        
        return filled, spent_money

    @error_log
    async def _update_seller_balance_buy_match(
        self, 
        seller_id: str, 
        ticker: str, 
        executed_qty: int, 
        executed_price: int, 
        session: AsyncSession
    ) -> None:
        """Обновление баланса продавца при сопоставлении его ордера на продажу"""
        executed_amount = executed_qty * executed_price
        
        # Блокируем баланс продавца для обновления
        seller_asset_balance = await session.execute(
            select(Balance).where(
                Balance.user_id == seller_id, 
                Balance.ticker == ticker
            ).with_for_update()
        )
        seller_asset_balance = seller_asset_balance.scalar_one_or_none()
        
        seller_rub_balance = await session.execute(
            select(Balance).where(
                Balance.user_id == seller_id, 
                Balance.ticker == "RUB"
            ).with_for_update()
        )
        seller_rub_balance = seller_rub_balance.scalar_one_or_none()
        
        # Обновляем баланс продавца
        if seller_asset_balance:
            # Разблокируем активы, но не больше, чем заблокировано
            seller_asset_balance.blocked_amount -= min(executed_qty, seller_asset_balance.blocked_amount)
            
            # Убедимся, что не уйдем в отрицательный баланс
            if seller_asset_balance.amount < executed_qty:
                error_log(f"Предотвращено отрицательное значение баланса активов: available={seller_asset_balance.amount}, required={executed_qty}")
                executed_qty = seller_asset_balance.amount
                
            seller_asset_balance.amount -= executed_qty
            error_log(f"Списано у продавца: {executed_qty} {ticker}, новый баланс: {seller_asset_balance.amount} {ticker}")
        
        if seller_rub_balance:
            seller_rub_balance.amount += executed_amount
            error_log(f"Добавлено продавцу: {executed_amount} RUB, новый баланс: {seller_rub_balance.amount} RUB")
        else:
            # Создаем новый баланс если не существует
            new_rub_balance = Balance(
                user_id=seller_id,
                ticker="RUB",
                amount=executed_amount,
                blocked_amount=0
            )
            session.add(new_rub_balance)
            error_log(f"Создан новый баланс RUB для продавца: {executed_amount} RUB")

    @error_log
    async def _process_sell_matching(
        self, 
        user_id: str,
        ticker: str, 
        qty: int, 
        price: int | None, 
        rub_balance: Balance, 
        asset_balance: Balance, 
        session: AsyncSession
    ) -> tuple:
        """Обработка сопоставления ордера на продажу с существующими ордерами на покупку"""
        is_limit = price is not None
        
        # Для рыночных ордеров проверяем, есть ли вообще предложения на покупку
        if not is_limit:
            # Проверяем наличие ордеров на покупку для данного тикера
            buy_count = await session.execute(
                select(func.count()).where(
                    Order.ticker == ticker,
                    Order.direction == OrderDirection.BUY,
                    Order.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED])
                )
            )
            buy_count = buy_count.scalar_one()
            
            if buy_count == 0:
                error_log(f"Нет активных ордеров на покупку для тикера {ticker}. Рыночный ордер на продажу отменен.")
                return 0, 0
        
        matched_orders = await match_buy_orders(ticker, qty, price, session)
        filled = matched_orders["filled_qty"]
        earned_money = matched_orders["earned_money"]
        
        if filled > 0:
            # Обновляем балансы для каждого покупателя, с которым был матчинг
            for buyer_order_id, execution_info in matched_orders.get("executions", {}).items():
                await self._update_buyer_balance_sell_match(
                    execution_info["user_id"],
                    ticker,
                    execution_info["qty"],
                    execution_info["price"],
                    session
                )
            
            # Обновляем баланс продавца
            asset_balance.blocked_amount -= min(filled, asset_balance.blocked_amount)  # Разблокируем использованные активы, но не больше, чем заблокировано
            asset_balance.amount -= filled  # Списываем проданные активы
            
            # Логируем обновление баланса продавца
            error_log(f"Обновление баланса продавца: списано {filled} {ticker}, осталось {asset_balance.amount} (заблокировано {asset_balance.blocked_amount})")
            
            if rub_balance:
                rub_balance.amount += earned_money  # Добавляем полученные средства
                error_log(f"Добавлено на счет продавца {earned_money} RUB, новый баланс: {rub_balance.amount} RUB")
            else:
                # Создаем новый баланс RUB
                new_rub_balance = Balance(
                    user_id=user_id,
                    ticker="RUB",
                    amount=earned_money,
                    blocked_amount=0
                )
                session.add(new_rub_balance)
                error_log(f"Создан новый счет для продавца с балансом {earned_money} RUB")
        
        # Если это рыночная заявка или полностью исполненная лимитная
        if not is_limit or filled == qty:
            # Если осталась блокировка, разблокируем лишнее
            if asset_balance.blocked_amount > 0 and (not is_limit or filled < qty):
                remaining_block = qty - filled
                # Не разблокируем больше, чем есть в blocked_amount
                actual_unblock = min(remaining_block, asset_balance.blocked_amount)
                asset_balance.blocked_amount -= actual_unblock
                error_log(f"Разблокировано {actual_unblock} {ticker} после исполнения/отмены ордера")
        
        return filled, earned_money

    @error_log
    async def _update_buyer_balance_sell_match(
        self, 
        buyer_id: str, 
        ticker: str, 
        executed_qty: int, 
        executed_price: int, 
        session: AsyncSession
    ) -> None:
        """Обновление баланса покупателя при сопоставлении его ордера на покупку"""
        executed_amount = executed_qty * executed_price
        
        # Блокируем баланс покупателя для обновления
        buyer_asset_balance = await session.execute(
            select(Balance).where(
                Balance.user_id == buyer_id, 
                Balance.ticker == ticker
            ).with_for_update()
        )
        buyer_asset_balance = buyer_asset_balance.scalar_one_or_none()
        
        buyer_rub_balance = await session.execute(
            select(Balance).where(
                Balance.user_id == buyer_id, 
                Balance.ticker == "RUB"
            ).with_for_update()
        )
        buyer_rub_balance = buyer_rub_balance.scalar_one_or_none()
        
        # Обновляем баланс покупателя
        if buyer_rub_balance:
            # Разблокируем средства, но не больше, чем заблокировано
            buyer_rub_balance.blocked_amount -= min(executed_amount, buyer_rub_balance.blocked_amount)
            
            # Убедимся, что не уйдем в отрицательный баланс
            if buyer_rub_balance.amount < executed_amount:
                error_log(f"Предотвращено отрицательное значение баланса: available={buyer_rub_balance.amount}, required={executed_amount}")
                executed_amount = buyer_rub_balance.amount
                
            buyer_rub_balance.amount -= executed_amount
            error_log(f"Списано у покупателя: {executed_amount} RUB, новый баланс: {buyer_rub_balance.amount} RUB")
        
        if buyer_asset_balance:
            buyer_asset_balance.amount += executed_qty
            error_log(f"Добавлено покупателю: {executed_qty} {ticker}, новый баланс: {buyer_asset_balance.amount} {ticker}")
        else:
            # Создаем новый баланс если не существует
            new_asset_balance = Balance(
                user_id=buyer_id,
                ticker=ticker,
                amount=executed_qty,
                blocked_amount=0
            )
            session.add(new_asset_balance)
            error_log(f"Создан новый баланс для покупателя: {executed_qty} {ticker}")

    @error_log
    async def _set_order_status(
        self, 
        order: Order, 
        is_limit: bool, 
        filled: int, 
        qty: int
    ) -> None:
        """Установка статуса ордера в зависимости от результатов сопоставления"""
        if not is_limit:
            if filled == 0:
                order.status = OrderStatus.CANCELLED
            elif filled < qty:
                order.status = OrderStatus.PARTIALLY_EXECUTED
            else:
                order.status = OrderStatus.EXECUTED
        else:
            if filled == qty:
                order.status = OrderStatus.EXECUTED
            elif filled > 0:
                order.status = OrderStatus.PARTIALLY_EXECUTED
            # Иначе статус остается NEW
                
    async def get_orderbook(self, ticker: str, session: AsyncSession, limit: int = 100) -> dict:
        """Получение биржевого стакана - делегируем в специализированный модуль"""
        return await get_orderbook(ticker, session, limit)


# Создаем единственный экземпляр для использования в приложении
order_crud = CRUDOrder() 