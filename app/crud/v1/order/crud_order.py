from uuid import uuid4

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
    deduct_assets
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
    async def create_order(
            self,
            user_id: str,
            body: LimitOrderBody | MarketOrderBody,
            session: AsyncSession,
    ) -> Order:
        """Создание нового ордера с учетом сопоставления с существующими ордерами"""
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
        
        try:
            # Сначала проверяем достаточность баланса без блокировки строк
            # Это делается вне транзакции
            if direction == OrderDirection.BUY and is_limit:
                # Проверяем наличие достаточного количества RUB для покупки
                # Для рыночных ордеров на покупку проверка не нужна, так как цена неизвестна
                rub_check = await session.execute(
                    select(Balance).where(
                        Balance.user_id == user_id, 
                        Balance.ticker == "RUB"
                    )
                )
                rub_balance_check = rub_check.scalar_one_or_none()
                
                if not rub_balance_check or rub_balance_check.amount - rub_balance_check.blocked_amount < qty * price:
                    available = rub_balance_check.amount - rub_balance_check.blocked_amount if rub_balance_check else 0
                    required = qty * price
                    error_msg = f"Недостаточно средств для создания ордера на покупку. Требуется: {required} RUB, доступно: {available} RUB"
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
            
            # Устанавливаем advisory lock для пользователя и тикера
            # Это поможет избежать deadlock при сложных операциях с несколькими балансами
            combined_hash = int(hash(f"{user_id}:{ticker}")) % 2147483647  # Ограничиваем значение хеша для PostgreSQL
            await session.execute(text(f"SELECT pg_advisory_xact_lock({combined_hash})"))
            error_log(f"Получена advisory lock для user_id={user_id}, ticker={ticker}, hash={combined_hash}")
            
            # Блокируем строки баланса для нужных валют
            if direction == OrderDirection.BUY:
                # Блокируем RUB (для покупки) и актив (для получения)
                rub_balance = await session.execute(
                    select(Balance).where(
                        Balance.user_id == user_id, 
                        Balance.ticker == "RUB"
                    ).with_for_update()
                )
                rub_balance = rub_balance.scalar_one_or_none()
                
                asset_balance = await session.execute(
                    select(Balance).where(
                        Balance.user_id == user_id, 
                        Balance.ticker == ticker
                    ).with_for_update()
                )
                asset_balance = asset_balance.scalar_one_or_none()
                
                # Повторная проверка баланса после блокировки (на случай изменений)
                # Только для лимитных ордеров, так как для рыночных цена неизвестна
                if is_limit and (not rub_balance or rub_balance.amount - rub_balance.blocked_amount < qty * price):
                    available = rub_balance.amount - rub_balance.blocked_amount if rub_balance else 0
                    required = qty * price
                    error_msg = f"Недостаточно средств для создания ордера на покупку. Требуется: {required} RUB, доступно: {available} RUB"
                    error_log(error_msg)
                    raise ValueError(error_msg)
                
                # Блокируем средства на покупку (только для лимитных ордеров)
                if is_limit:
                    rub_balance.blocked_amount += qty * price
                    error_log(f"Заблокировано {qty * price} RUB для покупки {qty} {ticker}")
                
            elif direction == OrderDirection.SELL:
                # Блокируем актив (для продажи) и RUB (для получения)
                asset_balance = await session.execute(
                    select(Balance).where(
                        Balance.user_id == user_id, 
                        Balance.ticker == ticker
                    ).with_for_update()
                )
                asset_balance = asset_balance.scalar_one_or_none()
                
                rub_balance = await session.execute(
                    select(Balance).where(
                        Balance.user_id == user_id, 
                        Balance.ticker == "RUB"
                    ).with_for_update()
                )
                rub_balance = rub_balance.scalar_one_or_none()
                
                # Повторная проверка баланса после блокировки (на случай изменений)
                if not asset_balance or asset_balance.amount - asset_balance.blocked_amount < qty:
                    available = asset_balance.amount - asset_balance.blocked_amount if asset_balance else 0
                    error_msg = f"Недостаточно средств для создания ордера на продажу. Требуется: {qty} {ticker}, доступно: {available} {ticker}"
                    error_log(error_msg)
                    raise ValueError(error_msg)
                
                # Блокируем активы для продажи
                asset_balance.blocked_amount += qty
                error_log(f"Заблокировано {qty} {ticker} для продажи")
            
            # Создаем запись ордера
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
            
            # Пытаемся исполнить ордер сразу (матчинг)
            if direction == OrderDirection.BUY:
                # Пытаемся сопоставить с заявками на продажу
                matched_orders = await match_sell_orders(ticker, qty, price, session)
                filled = matched_orders["filled_qty"]
                spent_money = matched_orders["spent_money"]
                
                if filled > 0:
                    # Обновляем балансы для каждого продавца, с которым был матчинг
                    for seller_order_id, execution_info in matched_orders.get("executions", {}).items():
                        seller_id = execution_info["user_id"]
                        executed_qty = execution_info["qty"]
                        executed_price = execution_info["price"]
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
                            seller_asset_balance.blocked_amount -= min(executed_qty, seller_asset_balance.blocked_amount)  # Не уходим в минус
                            seller_asset_balance.amount -= executed_qty
                        
                        if seller_rub_balance:
                            seller_rub_balance.amount += executed_amount
                        else:
                            # Создаем новый баланс если не существует
                            new_rub_balance = Balance(
                                user_id=seller_id,
                                ticker="RUB",
                                amount=executed_amount,
                                blocked_amount=0
                            )
                            session.add(new_rub_balance)
                    
                    # Обновляем баланс покупателя
                    if is_limit:
                        # Разблокируем потраченные средства для лимитного ордера
                        rub_balance.blocked_amount -= min(spent_money, rub_balance.blocked_amount)  # Не уходим в минус
                    
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
                
                # Устанавливаем статус ордера
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
            
            elif direction == OrderDirection.SELL:
                # Пытаемся сопоставить с заявками на покупку
                matched_orders = await match_buy_orders(ticker, qty, price, session)
                filled = matched_orders["filled_qty"]
                earned_money = matched_orders["earned_money"]
                
                if filled > 0:
                    # Обновляем балансы для каждого покупателя, с которым был матчинг
                    for buyer_order_id, execution_info in matched_orders.get("executions", {}).items():
                        buyer_id = execution_info["user_id"]
                        executed_qty = execution_info["qty"]
                        executed_price = execution_info["price"]
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
                            buyer_rub_balance.blocked_amount -= min(executed_amount, buyer_rub_balance.blocked_amount)  # Не уходим в минус
                            buyer_rub_balance.amount -= executed_amount
                        
                        if buyer_asset_balance:
                            buyer_asset_balance.amount += executed_qty
                        else:
                            # Создаем новый баланс если не существует
                            new_asset_balance = Balance(
                                user_id=buyer_id,
                                ticker=ticker,
                                amount=executed_qty,
                                blocked_amount=0
                            )
                            session.add(new_asset_balance)
                    
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
                
                # Устанавливаем статус ордера
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
            
            # Обновляем количество исполненных единиц ордера
            order.filled = filled
            
            # Создаем запись о транзакции, если были исполнения
            if filled > 0:
                # Здесь можно добавить код для создания записей в таблице транзакций
                # ...
                error_log(f"Ордер {order_id} исполнен на количество {filled} из {qty}")
            
            # Делаем коммит транзакции
            await session.commit()
            return order
        except Exception as e:
            error_log(f"Ошибка при создании ордера: {str(e)}")
            # Пробуем сделать rollback
            try:
                await session.rollback()
            except Exception as rollback_error:
                error_log(f"Ошибка при откате транзакции: {str(rollback_error)}")
            raise ValueError(f"Ошибка при создании ордера: {str(e)}")

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
            
            # Если статус не изменился, просто возвращаем заявку
            if order.status == new_status:
                return order
            
            # Если заявка уже отменена или исполнена, не позволяем менять статус
            if order.status in [OrderStatus.CANCELLED, OrderStatus.EXECUTED]:
                raise ValueError(f"Нельзя изменить статус заявки в статусе {order.status}")
            
            # Меняем статус заявки
            old_status = order.status
            order.status = new_status
            
            # Если заявка отменяется или исполняется полностью, разблокируем средства
            if new_status in [OrderStatus.CANCELLED, OrderStatus.EXECUTED]:                
                if order.direction == OrderDirection.BUY:
                    # Разблокируем деньги у покупателя только для лимитных ордеров
                    # Для рыночных ордеров price будет None
                    remaining_qty = order.qty - (order.filled or 0)
                    if remaining_qty > 0 and order.price is not None:
                        remaining_cost = remaining_qty * order.price
                        try:
                            await balance_crud.unblock_funds(order.user_id, "RUB", remaining_cost, session)
                            error_log(f"Разблокировано средств: {remaining_cost} RUB для пользователя {order.user_id}")
                        except ValueError as e:
                            error_log(f"Ошибка при разблокировке средств: {str(e)}")
                
                elif order.direction == OrderDirection.SELL:
                    # Разблокируем активы у продавца только для лимитных ордеров
                    # Для рыночных ордеров нет заблокированных активов
                    remaining_qty = order.qty - (order.filled or 0)
                    if remaining_qty > 0 and order.price is not None:
                        try:
                            await balance_crud.unblock_assets(order.user_id, order.ticker, remaining_qty, session)
                            error_log(f"Разблокировано активов: {remaining_qty} {order.ticker} для пользователя {order.user_id}")
                        except ValueError as e:
                            error_log(f"Ошибка при разблокировке активов: {str(e)}")
        
            # Делаем коммит внешней транзакции
            await session.commit()
            return order
        except Exception as e:
            error_log(f"Ошибка при обновлении статуса ордера: {str(e)}")
            await session.rollback()
            raise ValueError(f"Ошибка при обновлении статуса ордера: {str(e)}")

    async def get_orderbook(self, ticker: str, session: AsyncSession, limit: int = 100) -> dict:
        """Получение биржевого стакана - делегируем в специализированный модуль"""
        return await get_orderbook(ticker, session, limit)


# Создаем единственный экземпляр для использования в приложении
order_crud = CRUDOrder() 