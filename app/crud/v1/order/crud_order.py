from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, desc, asc
from datetime import datetime

from app.core.logs.logs import error_logger, error_log
from app.crud.v1.order.base import CRUDOrderBase
from app.crud.v1.order.crud_order_v2 import order_crud_v2
from app.crud.v1.order.market_data import get_orderbook
from app.crud.v1.balance import balance_crud
from app.models.order import Order, OrderStatus, OrderDirection, OrderBookLevels
from app.models.transaction import Transaction
from app.models.balance import Balance


class CRUDOrder(CRUDOrderBase):
    """Класс для работы с ордерами"""

    async def get_orderbook(self, ticker: str, session: AsyncSession, limit: int = 100,
                            levels: OrderBookLevels = OrderBookLevels.ALL) -> dict:
        """Получение биржевого стакана - делегируем в специализированный модуль"""
        return await get_orderbook(ticker, session, limit, levels)

    async def create_order(self, user_id: str, direction: OrderDirection, ticker: str,
                           qty: int, price: int = None, session: AsyncSession = None) -> Order:
        """
        Создание заявки на бирже

        Args:
            user_id: идентификатор пользователя
            direction: направление заявки (BUY или SELL)
            ticker: тикер инструмента
            qty: количество
            price: цена (для лимитной заявки)
            session: сессия БД

        Returns:
            Созданная заявка
        """
        if direction == OrderDirection.SELL:
            return await self._process_sell_order(
                user_id=user_id,
                ticker=ticker,
                qty=qty,
                price=price,
                session=session
            )
        else:  # BUY
            return await self._process_buy_order(
                user_id=user_id,
                ticker=ticker,
                qty=qty,
                price=price,
                session=session
            )

    async def _find_matching_orders(self, ticker: str, direction: OrderDirection,
                                    price: int = None, limit: int = 100,
                                    session: AsyncSession = None) -> list:
        """
        Поиск подходящих встречных заявок

        Args:
            ticker: тикер инструмента
            direction: направление заявки (противоположное направление будет искаться)
            price: цена для сопоставления
            limit: максимальное количество заявок
            session: сессия БД

        Returns:
            Список найденных заявок
        """
        # Определяем противоположное направление для поиска
        opposite_direction = OrderDirection.BUY if direction == OrderDirection.SELL else OrderDirection.SELL

        # Формируем базовый запрос
        stmt = select(Order).where(
            and_(
                Order.ticker == ticker,
                Order.direction == opposite_direction,
                or_(
                    Order.status == OrderStatus.NEW,
                    Order.status == OrderStatus.PARTIALLY_EXECUTED
                )
            )
        )

        # Если указана цена, добавляем условие по цене
        if price is not None:
            if direction == OrderDirection.SELL:
                # Для продажи ищем заявки на покупку с ценой >= нашей цены
                stmt = stmt.where(Order.price >= price)
            else:
                # Для покупки ищем заявки на продажу с ценой <= нашей цены
                stmt = stmt.where(Order.price <= price)

        # Сортируем по цене и времени создания (лучшая цена в начале, затем по времени создания)
        if opposite_direction == OrderDirection.BUY:
            # Для встречных заявок на покупку - сортируем от большей цены к меньшей (продаем тому, кто предлагает больше)
            stmt = stmt.order_by(desc(Order.price), asc(Order.created_at))
        else:
            # Для встречных заявок на продажу - сортируем от меньшей цены к большей (покупаем у того, кто предлагает дешевле)
            stmt = stmt.order_by(asc(Order.price), asc(Order.created_at))

        stmt = stmt.limit(limit)

        result = await session.execute(stmt)
        return result.scalars().all()

    async def _update_counterparty_order(self, order: Order, executed_qty: int,
                                         session: AsyncSession) -> None:
        """
        Обновление заявки контрагента

        Args:
            order: заявка для обновления
            executed_qty: количество, которое было исполнено
            session: сессия БД
        """
        # Обновляем количество исполненного объема
        order.filled = (order.filled or 0) + executed_qty

        # Обновляем статус заявки
        if order.filled >= order.qty:
            order.status = OrderStatus.EXECUTED
        else:
            order.status = OrderStatus.PARTIALLY_EXECUTED

        # Разблокируем средства у контрагента в соответствии с исполненным объемом
        if order.direction == OrderDirection.BUY:
            # Разблокируем рубли у покупателя
            if order.price is not None:  # Для лимитной заявки
                amount_to_unblock = executed_qty * order.price
                await balance_crud.unblock_funds(
                    user_id=order.user_id,
                    ticker="RUB",
                    amount=amount_to_unblock,
                    async_session=session
                )

                # Списываем рубли
                await balance_crud.withdraw(
                    user_id=order.user_id,
                    ticker="RUB",
                    amount=executed_qty * order.price,
                    async_session=session
                )

                # Начисляем тикеры
                await balance_crud.deposit(
                    user_id=order.user_id,
                    ticker=order.ticker,
                    amount=executed_qty,
                    async_session=session
                )
        else:  # SELL
            # Разблокируем тикеры у продавца
            await balance_crud.unblock_assets(
                user_id=order.user_id,
                ticker=order.ticker,
                qty=executed_qty,
                async_session=session
            )

            # Списываем тикеры
            await balance_crud.withdraw(
                user_id=order.user_id,
                ticker=order.ticker,
                amount=executed_qty,
                async_session=session
            )

            # Начисляем рубли
            if order.price is not None:  # Для лимитной заявки
                await balance_crud.deposit(
                    user_id=order.user_id,
                    ticker="RUB",
                    amount=executed_qty * order.price,
                    async_session=session
                )

    async def _create_cancelled_order(self, user_id: str, direction: OrderDirection, ticker: str, qty: int,
                                      price: int = None, session: AsyncSession = None) -> Order:
        """
        Создание заявки в статусе ОТМЕНЕНА

        Args:
            user_id: идентификатор пользователя
            direction: направление заявки
            ticker: тикер инструмента
            qty: количество
            price: цена (для лимитной заявки)
            session: сессия БД

        Returns:
            Созданная заявка
        """
        order = Order(
            user_id=user_id,
            direction=direction,
            ticker=ticker,
            qty=qty,
            price=price,
            status=OrderStatus.CANCELLED,
            filled=0
        )
        session.add(order)
        await session.flush()
        await session.commit()
        return order

    async def _create_transaction_and_deposit(self, user_id: str, ticker: str, executable_qty: int,
                                              price: int, receiver_ticker: str, session: AsyncSession) -> tuple:
        """
        Создание транзакции и начисление средств

        Args:
            user_id: идентификатор пользователя
            ticker: тикер транзакции
            executable_qty: исполняемое количество
            price: цена исполнения
            receiver_ticker: тикер получателя средств (RUB для продажи, ticker для покупки)
            session: сессия БД

        Returns:
            tuple: (сумма транзакции, исполненное количество)
        """
        # Проверяем, что количество положительное
        if executable_qty <= 0:
            return 0, 0

        # Создаем транзакцию
        transaction = Transaction(
            user_id=user_id,
            ticker=ticker,
            amount=executable_qty,
            price=price,
            timestamp=datetime.utcnow()
        )
        session.add(transaction)

        # Делаем flush, чтобы transaction получил id из базы
        await session.flush()

        # Начисляем средства
        transaction_amount = executable_qty * price

        if receiver_ticker == "RUB":
            # Для продажи - начисляем рубли
            await balance_crud.deposit(
                user_id=user_id,
                ticker=receiver_ticker,
                amount=transaction_amount,
                async_session=session
            )
            return transaction_amount, executable_qty
        else:
            # Для покупки - начисляем тикеры
            await balance_crud.deposit(
                user_id=user_id,
                ticker=receiver_ticker,
                amount=executable_qty,
                async_session=session
            )
            return transaction_amount, executable_qty

    async def _create_order(self, user_id: str, direction: OrderDirection, ticker: str,
                            qty: int, price: int, status: OrderStatus, filled: int,
                            session: AsyncSession) -> Order:
        """
        Создание заявки с указанными параметрами

        Args:
            user_id: идентификатор пользователя
            direction: направление заявки
            ticker: тикер инструмента
            qty: количество
            price: цена
            status: статус заявки
            filled: исполненное количество
            session: сессия БД

        Returns:
            Созданная заявка
        """
        order = Order(
            user_id=user_id,
            direction=direction,
            ticker=ticker,
            qty=qty,
            price=price,
            status=status,
            filled=filled
        )
        session.add(order)
        await session.flush()
        await session.commit()
        return order

    async def _determine_order_status(self, executed_qty: int, qty: int) -> OrderStatus:
        """
        Определение статуса заявки на основе исполненного количества

        Args:
            executed_qty: исполненное количество
            qty: общее количество

        Returns:
            Статус заявки
        """
        if executed_qty <= 0:
            return OrderStatus.NEW
        elif executed_qty >= qty:
            return OrderStatus.EXECUTED
        else:
            return OrderStatus.PARTIALLY_EXECUTED

    async def _match_orders(self, user_id: str, ticker: str, qty: int, price_levels: list,
                            is_buy: bool, price: int = None, session: AsyncSession = None) -> tuple:
        """
        Сопоставление заявок - исполнение заявки против существующих в стакане

        Args:
            user_id: идентификатор пользователя
            ticker: тикер инструмента
            qty: требуемое количество для исполнения
            price_levels: уровни цен стакана (bid_levels для продажи, ask_levels для покупки)
            is_buy: флаг направления (True - покупка, False - продажа)
            price: цена нашей заявки (для лимитного ордера)
            session: сессия БД

        Returns:
            tuple: (исполненное количество, потраченная/полученная сумма)
        """
        executed_qty = 0
        total_amount = 0

        if not price_levels:
            return executed_qty, total_amount

        # Направление нашей заявки
        direction = OrderDirection.BUY if is_buy else OrderDirection.SELL

        # Находим заявки контрагентов в БД
        counterparty_orders = await self._find_matching_orders(
            ticker=ticker,
            direction=direction,
            price=price,
            session=session
        )

        # Выполняем заявки контрагентов в соответствии с приоритетом
        remaining_qty = qty

        # Сначала обрабатываем заявки из базы данных по приоритету цены и времени
        for counterparty_order in counterparty_orders:
            if remaining_qty <= 0:
                break

            # Сколько можно исполнить из этой заявки
            unfilled_qty = counterparty_order.qty - (counterparty_order.filled or 0)
            match_qty = min(remaining_qty, unfilled_qty)

            if match_qty <= 0:
                continue

            # Цена исполнения - цена из заявки контрагента (лучшая цена для нас)
            execution_price = counterparty_order.price

            # Создаем транзакцию и начисляем средства
            if is_buy:
                # Покупка: списываем рубли, начисляем тикеры
                transaction_amount, exec_qty = await self._create_transaction_and_deposit(
                    user_id=user_id,
                    ticker=ticker,
                    executable_qty=match_qty,
                    price=execution_price,
                    receiver_ticker=ticker,  # Покупаем тикер
                    session=session
                )
            else:
                # Продажа: списываем тикеры, начисляем рубли
                transaction_amount, exec_qty = await self._create_transaction_and_deposit(
                    user_id=user_id,
                    ticker=ticker,
                    executable_qty=match_qty,
                    price=execution_price,
                    receiver_ticker="RUB",  # Получаем рубли
                    session=session
                )

            # Обновляем заявку контрагента
            await self._update_counterparty_order(
                order=counterparty_order,
                executed_qty=match_qty,
                session=session
            )

            executed_qty += exec_qty
            total_amount += transaction_amount
            remaining_qty -= exec_qty

        # Если остается невыполненное количество, выполняем заявки из стакана
        # Эта часть нужна, если в BD нет соответствующих заявок или их недостаточно
        if remaining_qty > 0:
            for level in price_levels:
                if remaining_qty <= 0:
                    break

                level_price = level["price"]
                level_qty = level["qty"]

                # Проверяем, что уровень еще имеет ненулевое количество
                if level_qty <= 0:
                    continue

                # Сколько можно исполнить на этом уровне цены
                executable_qty = min(remaining_qty, level_qty)

                # Создаем транзакцию и начисляем средства
                if is_buy:
                    # Покупка: списываем рубли, начисляем тикеры
                    transaction_amount, exec_qty = await self._create_transaction_and_deposit(
                        user_id=user_id,
                        ticker=ticker,
                        executable_qty=executable_qty,
                        price=level_price,
                        receiver_ticker=ticker,  # Покупаем тикер
                        session=session
                    )
                else:
                    # Продажа: списываем тикеры, начисляем рубли
                    transaction_amount, exec_qty = await self._create_transaction_and_deposit(
                        user_id=user_id,
                        ticker=ticker,
                        executable_qty=executable_qty,
                        price=level_price,
                        receiver_ticker="RUB",  # Получаем рубли
                        session=session
                    )

                # Учитываем исполненное количество и сумму
                executed_qty += exec_qty
                total_amount += transaction_amount
                remaining_qty -= exec_qty

        await session.commit()
        return executed_qty, total_amount

    async def _process_sell_order(self, user_id: str, ticker: str, qty: int,
                                  price: int = None, session: AsyncSession = None) -> Order:
        """
        Обработка заявки на продажу

        Args:
            user_id: идентификатор пользователя
            ticker: тикер инструмента
            qty: количество
            price: цена (для лимитной заявки)
            session: сессия БД

        Returns:
            Созданная заявка
        """
        # 1. Проверяем наличие тикеров у пользователя
        available_amount = await balance_crud.get_user_available_balance(
            user_id=user_id,
            ticker=ticker,
            async_session=session
        )

        if available_amount < qty:
            raise ValueError(f'Недостаточно {ticker} на балансе для создания заявки')

        # 2. Определяем тип заявки (лимитная или рыночная)
        is_market_order = price is None

        if is_market_order:
            return await order_crud_v2.sell_market(user_id=user_id, ticker=ticker, qty=qty, session=session)
        else:
            return await order_crud_v2.sell_limit(user_id=user_id, ticker=ticker, qty=qty, price=price, session=session)

        # if is_market_order:
        #     # 3. Рыночная заявка - проверяем наличие спроса (заявок на покупку)
        #     orderbook = await self.get_orderbook(ticker=ticker, session=session, levels=OrderBookLevels.BID)
        #     bid_levels = orderbook["bid_levels"]
        #
        #     if not bid_levels:
        #         # 4. Нет заявок на покупку - отменяем заявку
        #         return await self._create_cancelled_order(
        #             user_id=user_id,
        #             direction=OrderDirection.SELL,
        #             ticker=ticker,
        #             qty=qty,
        #             price=None,
        #             session=session
        #         )
        #
        #     # Проверяем, хватит ли заявок на покупку
        #     total_available_qty = sum(level["qty"] for level in bid_levels)
        #
        #     if total_available_qty < qty:
        #         # Если доступно хоть какое-то количество, исполняем частично
        #         if total_available_qty > 0:
        #             # Блокируем тикеры на балансе для доступного количества
        #             await balance_crud.block_assets(
        #                 user_id=user_id,
        #                 ticker=ticker,
        #                 qty=total_available_qty,  # Только доступное количество
        #                 async_session=session
        #             )
        #
        #             # Исполняем заявку на доступное количество
        #             executed_qty, total_received = await self._match_orders(
        #                 user_id=user_id,
        #                 ticker=ticker,
        #                 qty=total_available_qty,  # Только на доступное количество
        #                 price_levels=bid_levels,
        #                 is_buy=False,  # Продажа
        #                 session=session
        #             )
        #
        #             # Разблокируем и списываем тикеры
        #             await balance_crud.unblock_assets(
        #                 user_id=user_id,
        #                 ticker=ticker,
        #                 qty=total_available_qty,
        #                 async_session=session
        #             )
        #
        #             await balance_crud.withdraw(
        #                 user_id=user_id,
        #                 ticker=ticker,
        #                 amount=total_available_qty,
        #                 async_session=session
        #             )
        #
        #             # Создаем частично исполненную заявку
        #             return await self._create_order(
        #                 user_id=user_id,
        #                 direction=OrderDirection.SELL,
        #                 ticker=ticker,
        #                 qty=qty,
        #                 price=None,  # Рыночная заявка
        #                 status=OrderStatus.PARTIALLY_EXECUTED,
        #                 filled=executed_qty,
        #                 session=session
        #             )
        #         else:
        #             # Если совсем нет заявок - отменяем
        #             return await self._create_cancelled_order(
        #                 user_id=user_id,
        #                 direction=OrderDirection.SELL,
        #                 ticker=ticker,
        #                 qty=qty,
        #                 price=None,
        #                 session=session
        #             )
        # else:
        #     # Лимитная заявка
        #     # 4. Блокируем тикеры
        #     await balance_crud.block_assets(
        #         user_id=user_id,
        #         ticker=ticker,
        #         qty=qty,
        #         async_session=session
        #     )
        #
        #     # 5-6. Сопоставляем данные
        #     orderbook = await self.get_orderbook(ticker=ticker, session=session, levels=OrderBookLevels.BID)
        #
        #     # Для продажи ищем заявки на покупку с ценой >= нашей цены (сортируем по убыванию цены)
        #     bid_levels = [level for level in orderbook["bid_levels"] if level["price"] >= price]
        #
        #     # Сортируем по убыванию цены, чтобы продать по наиболее высокой цене сначала
        #     bid_levels.sort(key=lambda x: x["price"], reverse=True)
        #
        #     # Проверяем, достаточно ли встречных заявок на покупку для полного исполнения
        #     total_available_qty = sum(level["qty"] for level in bid_levels)
        #
        #     # Определяем максимальное количество, которое можно исполнить сразу
        #     max_executable_qty = min(qty, total_available_qty)
        #
        #     # Исполняем подходящие заявки в пределах доступного количества
        #     executed_qty, total_received = await self._match_orders(
        #         user_id=user_id,
        #         ticker=ticker,
        #         qty=max_executable_qty,  # Используем ограниченное количество
        #         price_levels=bid_levels,
        #         is_buy=False,  # Продажа
        #         price=price,
        #         session=session
        #     )
        #
        #     # Разблокируем исполненную часть и списываем тикеры
        #     if executed_qty > 0:
        #         await balance_crud.unblock_assets(
        #             user_id=user_id,
        #             ticker=ticker,
        #             qty=executed_qty,
        #             async_session=session
        #         )
        #
        #         await balance_crud.withdraw(
        #             user_id=user_id,
        #             ticker=ticker,
        #             amount=executed_qty,
        #             async_session=session
        #         )
        #
        #     # Определяем статус заявки
        #     # Для лимитной заявки: даже если нет исполнения (executed_qty=0), она остаётся активной в статусе NEW
        #     status = await self._determine_order_status(executed_qty, qty)
        #
        #     # Создаем заявку
        #     return await self._create_order(
        #         user_id=user_id,
        #         direction=OrderDirection.SELL,
        #         ticker=ticker,
        #         qty=qty,
        #         price=price,
        #         status=status,
        #         filled=executed_qty,
        #         session=session
        #     )

    async def _process_buy_order(self, user_id: str, ticker: str, qty: int,
                                 price: int = None, session: AsyncSession = None) -> Order:
        """
        Обработка заявки на покупку

        Args:
            user_id: идентификатор пользователя
            ticker: тикер инструмента
            qty: количество
            price: цена (для лимитной заявки)
            session: сессия БД

        Returns:
            Созданная заявка
        """
        # Определяем тип заявки (лимитная или рыночная)
        is_market_order = price is None

        if is_market_order:
            return await order_crud_v2.buy_market(user_id, ticker, qty, session)
        else:
            return await order_crud_v2.buy_limit(user_id, ticker, qty, price, session)

        # if is_market_order:
        #     # Рыночная заявка - проверяем наличие предложения
        #     orderbook = await self.get_orderbook(ticker=ticker, session=session, levels=OrderBookLevels.ASK)
        #     ask_levels = orderbook["ask_levels"]
        #
        #     if not ask_levels:
        #         # Нет заявок на продажу - отменяем заявку
        #         return await self._create_cancelled_order(
        #             user_id=user_id,
        #             direction=OrderDirection.BUY,
        #             ticker=ticker,
        #             qty=qty,
        #             price=None,
        #             session=session
        #         )
        #
        #     # Считаем, сколько рублей потребуется
        #     required_amount = 0
        #     available_qty = 0
        #
        #     # Сортируем уровни по возрастанию цены, чтобы покупать сначала по самой низкой цене
        #     sorted_ask_levels = sorted(ask_levels, key=lambda x: x["price"])
        #
        #     for ask_level in sorted_ask_levels:
        #         ask_price = ask_level["price"]
        #         ask_qty = ask_level["qty"]
        #
        #         executable_qty = min(qty - available_qty, ask_qty)
        #         required_amount += executable_qty * ask_price
        #         available_qty += executable_qty
        #
        #         if available_qty >= qty:
        #             break
        #
        #     if available_qty < qty:
        #         # Недостаточно предложения - но не отменяем заявку сразу,
        #         # а пытаемся исполнить то, что есть
        #         if available_qty > 0:
        #             # Блокируем и выполняем рыночную заявку на доступное количество
        #             partial_required_amount = required_amount  # для имеющегося количества
        #
        #             # Проверяем наличие рублей на балансе
        #             available_rub = await balance_crud.get_user_available_balance(
        #                 user_id=user_id,
        #                 ticker="RUB",
        #                 async_session=session
        #             )
        #
        #             if available_rub < partial_required_amount:
        #                 raise ValueError('Недостаточно RUB на балансе для выполнения заявки')
        #
        #             # Блокируем рубли на балансе
        #             await balance_crud.block_funds(
        #                 user_id=user_id,
        #                 ticker="RUB",
        #                 amount=partial_required_amount,
        #                 async_session=session
        #             )
        #
        #             # Исполняем заявку на доступное количество
        #             executed_qty, spent_amount = await self._match_orders(
        #                 user_id=user_id,
        #                 ticker=ticker,
        #                 qty=available_qty,  # Ограничиваем доступным количеством
        #                 price_levels=sorted_ask_levels,
        #                 is_buy=True,  # Покупка
        #                 session=session
        #             )
        #
        #             # Разблокируем рубли и списываем потраченные
        #             await balance_crud.unblock_funds(
        #                 user_id=user_id,
        #                 ticker="RUB",
        #                 amount=partial_required_amount,
        #                 async_session=session
        #             )
        #
        #             await balance_crud.withdraw(
        #                 user_id=user_id,
        #                 ticker="RUB",
        #                 amount=spent_amount,
        #                 async_session=session
        #             )
        #
        #             # Создаем частично исполненную заявку
        #             return await self._create_order(
        #                 user_id=user_id,
        #                 direction=OrderDirection.BUY,
        #                 ticker=ticker,
        #                 qty=qty,
        #                 price=None,  # Рыночная заявка
        #                 status=OrderStatus.PARTIALLY_EXECUTED,
        #                 filled=executed_qty,
        #                 session=session
        #             )
        #         else:
        #             # Если вообще нет доступных тикеров - отменяем заявку
        #             return await self._create_cancelled_order(
        #                 user_id=user_id,
        #                 direction=OrderDirection.BUY,
        #                 ticker=ticker,
        #                 qty=qty,
        #                 price=None,
        #                 session=session
        #             )
        #
        #     # Для полного исполнения рыночного ордера, когда в стакане достаточно заявок на продажу
        #
        #     # Проверяем наличие рублей на балансе
        #     available_rub = await balance_crud.get_user_available_balance(
        #         user_id=user_id,
        #         ticker="RUB",
        #         async_session=session
        #     )
        #
        #     if available_rub < required_amount:
        #         raise ValueError('Недостаточно RUB на балансе для выполнения заявки')
        #
        #     # Блокируем рубли на балансе
        #     await balance_crud.block_funds(
        #         user_id=user_id,
        #         ticker="RUB",
        #         amount=required_amount,
        #         async_session=session
        #     )
        #
        #     # Исполняем заявку полностью
        #     executed_qty, spent_amount = await self._match_orders(
        #         user_id=user_id,
        #         ticker=ticker,
        #         qty=qty,
        #         price_levels=sorted_ask_levels,
        #         is_buy=True,
        #         session=session
        #     )
        #
        #     # Разблокируем рубли и списываем потраченные
        #     await balance_crud.unblock_funds(
        #         user_id=user_id,
        #         ticker="RUB",
        #         amount=required_amount,
        #         async_session=session
        #     )
        #
        #     await balance_crud.withdraw(
        #         user_id=user_id,
        #         ticker="RUB",
        #         amount=spent_amount,
        #         async_session=session
        #     )
        #
        #     # Создаем исполненную заявку
        #     return await self._create_order(
        #         user_id=user_id,
        #         direction=OrderDirection.BUY,
        #         ticker=ticker,
        #         qty=qty,
        #         price=None,  # Рыночная заявка
        #         status=OrderStatus.EXECUTED,
        #         filled=qty,
        #         session=session
        #     )
        # else:
        #     # Лимитная заявка
        #     # Считаем, сколько рублей нужно заблокировать
        #     required_amount = qty * price
        #
        #     # Проверяем наличие рублей
        #     available_rub = await balance_crud.get_user_available_balance(
        #         user_id=user_id,
        #         ticker="RUB",
        #         async_session=session
        #     )
        #
        #     if available_rub < required_amount:
        #         raise ValueError('Недостаточно RUB на балансе для создания заявки')
        #
        #     # Блокируем рубли
        #     await balance_crud.block_funds(
        #         user_id=user_id,
        #         ticker="RUB",
        #         amount=required_amount,
        #         async_session=session
        #     )
        #
        #     # Проверяем, можно ли исполнить заявку сразу
        #     orderbook = await self.get_orderbook(ticker=ticker, session=session, levels=OrderBookLevels.ASK)
        #
        #     # Для покупки ищем заявки на продажу с ценой <= нашей цены
        #     ask_levels = [level for level in orderbook["ask_levels"] if level["price"] <= price]
        #
        #     # Сортируем по возрастанию цены, чтобы покупать сначала по самой низкой цене
        #     ask_levels.sort(key=lambda x: x["price"])
        #
        #     # Проверяем, достаточно ли тикеров в стакане для полного исполнения заявки
        #     total_available_qty = sum(level["qty"] for level in ask_levels)
        #
        #     # Определяем максимальное количество, которое можно исполнить
        #     # Если доступных тикеров меньше, чем запрошено, ограничиваем исполняемое количество
        #     max_executable_qty = min(qty, total_available_qty)
        #
        #     # Исполняем подходящие заявки в пределах доступного количества
        #     executed_qty, spent_amount = await self._match_orders(
        #         user_id=user_id,
        #         ticker=ticker,
        #         qty=max_executable_qty,  # Используем ограниченное количество
        #         price_levels=ask_levels,
        #         is_buy=True,  # Покупка
        #         price=price,
        #         session=session
        #     )
        #
        #     # Разблокируем только часть средств, которая была фактически потрачена
        #     if executed_qty > 0:
        #         # Разблокируем сначала всю заблокированную сумму
        #         await balance_crud.unblock_funds(
        #             user_id=user_id,
        #             ticker="RUB",
        #             amount=required_amount,
        #             async_session=session
        #         )
        #
        #         # Списываем фактически потраченные средства
        #         await balance_crud.withdraw(
        #             user_id=user_id,
        #             ticker="RUB",
        #             amount=spent_amount,
        #             async_session=session
        #         )
        #
        #         # Если есть неисполненная часть заявки, блокируем средства заново только для оставшихся тикеров
        #         remaining_qty = qty - executed_qty
        #         if remaining_qty > 0:
        #             remaining_amount_to_block = remaining_qty * price
        #             await balance_crud.block_funds(
        #                 user_id=user_id,
        #                 ticker="RUB",
        #                 amount=remaining_amount_to_block,
        #                 async_session=session
        #             )
        #
        #     # Определяем статус заявки
        #     status = await self._determine_order_status(executed_qty, qty)
        #
        #     # Создаем заявку
        #     return await self._create_order(
        #         user_id=user_id,
        #         direction=OrderDirection.BUY,
        #         ticker=ticker,
        #         qty=qty,
        #         price=price,
        #         status=status,
        #         filled=executed_qty,
        #         session=session
        #     )

    async def cancel_order(self, order_id: str, session: AsyncSession) -> Order:
        """
        Отмена заявки и разблокировка средств

        Args:
            order_id: идентификатор заявки
            session: сессия БД

        Returns:
            Обновленная заявка
        """
        # Получаем заявку по ID
        order = await self.get(id=order_id, session=session)

        if not order:
            raise ValueError('Заявка не найдена')

        # Проверяем, что заявка может быть отменена
        if order.status not in [OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]:
            raise ValueError(f'Невозможно отменить заявку в статусе {order.status.value}')

        # Определяем количество невыполненных активов/средств
        unfilled_qty = order.qty - (order.filled or 0)

        if unfilled_qty <= 0:
            raise ValueError('В заявке нет невыполненной части для отмены')

        # Разблокируем средства в зависимости от направления заявки
        if order.direction == OrderDirection.SELL:
            # Разблокировка тикеров при отмене заявки на продажу
            await balance_crud.unblock_assets(
                user_id=order.user_id,
                ticker=order.ticker,
                qty=unfilled_qty,
                async_session=session
            )
        else:  # BUY
            # Разблокировка рублей при отмене заявки на покупку
            if order.price is not None:  # Только для лимитных заявок
                # Получаем текущие заблокированные средства
                balance_result = await session.execute(
                    select(Balance).where(
                        and_(
                            Balance.user_id == order.user_id,
                            Balance.ticker == "RUB"
                        )
                    )
                )
                balance = balance_result.scalar_one_or_none()

                if not balance:
                    raise ValueError('Баланс пользователя не найден')

                # Максимальное количество рублей, которое можно разблокировать
                max_to_unblock = min(
                    unfilled_qty * order.price,
                    balance.blocked_amount
                )

                if max_to_unblock > 0:
                    await balance_crud.unblock_funds(
                        user_id=order.user_id,
                        ticker="RUB",
                        amount=max_to_unblock,
                        async_session=session
                    )

        # Обновляем статус заявки
        order.status = OrderStatus.CANCELLED
        await session.commit()

        return order


# Создаем единственный экземпляр для использования в приложении
order_crud = CRUDOrder()
