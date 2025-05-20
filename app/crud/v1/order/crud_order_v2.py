import json
import sys
from typing import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, asc, update, desc
from datetime import datetime

from app.core.logs.logs import error_log, error_logger, info_logger
from app.crud.v1.order.base import CRUDOrderBase
from app.crud.v1.balance import balance_crud
from app.models.order import Order, OrderStatus, OrderDirection
from app.models.transaction import Transaction


class CRUDOrderV2(CRUDOrderBase):
    """Класс для работы с ордерами"""

    @error_log
    async def buy_market(
            self,
            user_id: str,
            ticker: str,
            qty: int,
            session: AsyncSession) -> Order:
        error_logger.error("start market buy order")
        # Находим заявки контрагентов в БД
        counterparty_orders = await self._get_sell_orders(
            ticker=ticker,
            user_id=user_id,
            session=session
        )

        user_balance = await balance_crud.get_user_ticker_balance(user_id, ticker="RUB", session=session)

        # Выполняем заявки контрагентов в соответствии с приоритетом
        remaining_qty = qty
        remaining_balance = user_balance

        # Сначала обрабатываем заявки из базы данных по приоритету цены и времени
        for counterparty_order in counterparty_orders:

            info_logger.info(
                f"exec remaining_qty: {remaining_qty}, counterparty_order: {counterparty_order.__dict__}")

            if remaining_qty <= 0:
                break

            buy_count = await self._try_fill(
                counterparty_order.id,
                max_amount=remaining_qty,
                max_price=remaining_balance,
                session=session)

            success_buy = await balance_crud.try_block_and_buy(
                user_buy_id=user_id,
                ticker_user_buy="RUB",
                amount_user_buy=buy_count * counterparty_order.price,

                user_sell_id=counterparty_order.user_id,
                ticker_user_sell=ticker,
                amount_user_sell=buy_count,

                session=session
            )
            if not success_buy:
                await self._release_fill(counterparty_order.id, buy_count, session)
                continue

            transaction = Transaction(
                user_id=user_id,
                ticker=ticker,
                amount=buy_count,
                price=counterparty_order.price,
                timestamp=datetime.utcnow()
            )
            session.add(transaction)
            await session.flush()
            # TODO откатить транзакцию, если будут с этим проблемы

            remaining_qty -= buy_count
            remaining_balance -= buy_count * counterparty_order.price

        if len(counterparty_orders) == 0:
            return await self._create_order(
                user_id=user_id,
                direction=OrderDirection.BUY,
                ticker=ticker,
                qty=qty,
                price=None,
                status=OrderStatus.CANCELLED,
                filled=0,
                session=session
            )

        if remaining_qty == 0:
            return await self._create_order(
                user_id=user_id,
                direction=OrderDirection.BUY,
                ticker=ticker,
                qty=qty,
                price=None,  # Рыночная заявка
                status=OrderStatus.EXECUTED,
                filled=qty,
                session=session
            )
        if remaining_qty > 0:
            return await self._create_order(
                user_id=user_id,
                direction=OrderDirection.BUY,
                ticker=ticker,
                qty=qty,
                price=None,  # Рыночная заявка
                status=OrderStatus.PARTIALLY_EXECUTED,
                filled=remaining_qty,
                session=session
            )

    @error_log
    async def buy_limit(
            self,
            user_id: str,
            ticker: str,
            qty: int,
            price: int,
            session: AsyncSession) -> Order:
        error_logger.error("start buy limit")

        success_block = await balance_crud.try_block_ticker(user_id, ticker="RUB", amount=qty * price, session=session)
        if not success_block:
            raise ValueError('Недостаточно RUB на балансе для создания заявки')

        # Находим заявки контрагентов в БД
        counterparty_orders = await self._get_sell_orders_by_price(
            ticker=ticker,
            price=price,
            user_id=user_id,
            session=session
        )

        # Выполняем заявки контрагентов в соответствии с приоритетом
        remaining_qty = qty
        remaining_balance = qty * price
        # Сначала обрабатываем заявки из базы данных по приоритету цены и времени
        for counterparty_order in counterparty_orders:
            info_logger.info(
                f"exec remaining_qty: {remaining_qty}, counterparty_order: {counterparty_order.__dict__}")

            if remaining_qty <= 0:
                break

            buy_count = await self._try_fill(
                counterparty_order.id,
                max_amount=remaining_qty,
                max_price=remaining_balance,
                session=session)

            success_buy = await balance_crud.commit_buy(
                user_buy_id=user_id,
                ticker_user_buy="RUB",
                amount_user_buy=buy_count * counterparty_order.price,

                user_sell_id=counterparty_order.user_id,
                ticker_user_sell=ticker,
                amount_user_sell=buy_count,

                session=session
            )
            if not success_buy:
                await self._release_fill(counterparty_order.id, buy_count, session)
                continue

            transaction = Transaction(
                user_id=user_id,
                ticker=ticker,
                amount=buy_count,
                price=counterparty_order.price,
                timestamp=datetime.utcnow()
            )
            session.add(transaction)
            await session.flush()

            remaining_qty -= buy_count
            remaining_balance -= buy_count * counterparty_order.price

        error_logger.error("2")
        if len(counterparty_orders) == 0:
            return await self._create_order(
                user_id=user_id,
                direction=OrderDirection.BUY,
                ticker=ticker,
                qty=qty,
                price=price,
                status=OrderStatus.NEW,
                filled=0,
                session=session
            )

        if remaining_qty == 0:
            return await self._create_order(
                user_id=user_id,
                direction=OrderDirection.BUY,
                ticker=ticker,
                qty=qty,
                price=price,
                status=OrderStatus.EXECUTED,
                filled=qty,
                session=session
            )
        if remaining_qty > 0:
            await balance_crud.release_ticker(user_id, ticker="RUB", amount=remaining_qty * price, session=session)
            return await self._create_order(
                user_id=user_id,
                direction=OrderDirection.BUY,
                ticker=ticker,
                qty=qty,
                price=price,
                status=OrderStatus.PARTIALLY_EXECUTED,
                filled=qty - remaining_qty,
                session=session
            )

    async def sell_market(
            self,
            user_id: str,
            ticker: str,
            qty: int,
            session: AsyncSession) -> Order:
        info_logger.info(f"start market sell order")

        success_block = await balance_crud.try_block_ticker(user_id, ticker=ticker, amount=qty, session=session)
        if not success_block:
            raise ValueError('Недостаточно RUB на балансе для создания заявки')

        # Находим заявки контрагентов в БД
        counterparty_orders = await self._get_buy_orders(
            ticker=ticker,
            user_id=user_id,
            session=session
        )

        # Выполняем заявки контрагентов в соответствии с приоритетом
        remaining_qty = qty

        # Сначала обрабатываем заявки из базы данных по приоритету цены и времени
        for counterparty_order in counterparty_orders:
            info_logger.info(
                f"exec remaining_qty: {remaining_qty}, counterparty_order: {counterparty_order.__dict__}")
            if remaining_qty <= 0:
                break

            # сколько можем продать по заявке
            # TODO запретить отменять заявки в таком состоянии
            sell_count = await self._try_fill(
                counterparty_order.id,
                remaining_qty,
                max_price=sys.maxsize,
                session=session)
            info_logger.info(f"sell_count: {sell_count}")

            success_buy = await balance_crud.commit_buy(
                user_buy_id=counterparty_order.user_id,
                ticker_user_buy="RUB",
                amount_user_buy=sell_count * counterparty_order.price,

                user_sell_id=user_id,
                ticker_user_sell=ticker,
                amount_user_sell=sell_count,

                session=session
            )
            if not success_buy:
                await self._release_fill(counterparty_order.id, sell_count, session)
                continue

            transaction = Transaction(
                user_id=counterparty_order.user_id,
                ticker=ticker,
                amount=sell_count,
                price=counterparty_order.price,
                timestamp=datetime.utcnow()
            )
            session.add(transaction)
            await session.flush()

            remaining_qty -= sell_count

        if len(counterparty_orders) == 0:
            return await self._create_order(
                user_id=user_id,
                direction=OrderDirection.SELL,
                ticker=ticker,
                qty=qty,
                price=None,
                status=OrderStatus.CANCELLED,
                filled=0,
                session=session
            )

        if remaining_qty == 0:
            return await self._create_order(
                user_id=user_id,
                direction=OrderDirection.SELL,
                ticker=ticker,
                qty=qty,
                price=None,  # Рыночная заявка
                status=OrderStatus.EXECUTED,
                filled=qty,
                session=session
            )
        if remaining_qty > 0:
            return await self._create_order(
                user_id=user_id,
                direction=OrderDirection.SELL,
                ticker=ticker,
                qty=qty,
                price=None,  # Рыночная заявка
                status=OrderStatus.PARTIALLY_EXECUTED,
                filled=remaining_qty,
                session=session
            )

    async def sell_limit(
            self,
            user_id: str,
            ticker: str,
            qty: int,
            price: int,
            session: AsyncSession) -> Order:
        info_logger.info("start limit sell order")

        success_block = await balance_crud.try_block_ticker(user_id, ticker=ticker, amount=qty, session=session)
        if not success_block:
            raise ValueError('Недостаточно RUB на балансе для создания заявки')

        # Находим заявки контрагентов в БД
        counterparty_orders = await self._get_buy_orders_by_price(
            ticker=ticker,
            price=price,
            user_id=user_id,
            session=session
        )

        # Выполняем заявки контрагентов в соответствии с приоритетом
        remaining_qty = qty

        # Сначала обрабатываем заявки из базы данных по приоритету цены и времени
        for counterparty_order in counterparty_orders:
            info_logger.info(
                f"exec remaining_qty: {remaining_qty}, counterparty_order: {counterparty_order.__dict__}")
            if remaining_qty <= 0:
                break

            sell_count = await self._try_fill(
                counterparty_order.id,
                max_amount=remaining_qty,
                max_price=sys.maxsize,
                session=session)
            info_logger.info(f"sell_count: {sell_count}")

            success_buy = await balance_crud.commit_buy(
                user_buy_id=counterparty_order.user_id,
                ticker_user_buy="RUB",
                amount_user_buy=sell_count * counterparty_order.price,

                user_sell_id=user_id,
                ticker_user_sell=ticker,
                amount_user_sell=sell_count,

                session=session
            )
            if not success_buy:
                await self._release_fill(counterparty_order.id, sell_count, session)
                continue
            info_logger.info(f"commit_buy")

            transaction = Transaction(
                user_id=counterparty_order.user_id,
                ticker=ticker,
                amount=sell_count,
                price=counterparty_order.price,
                timestamp=datetime.utcnow()
            )
            session.add(transaction)
            await session.flush()

            remaining_qty -= sell_count

        info_logger.info(f"finish remaining_qty: {remaining_qty}")
        if len(counterparty_orders) == 0:
            info_logger.info(f"create empty order")
            return await self._create_order(
                user_id=user_id,
                direction=OrderDirection.SELL,
                ticker=ticker,
                qty=qty,
                price=price,
                status=OrderStatus.NEW,
                filled=0,
                session=session
            )

        if remaining_qty == 0:
            info_logger.info(f"create executed order")
            return await self._create_order(
                user_id=user_id,
                direction=OrderDirection.SELL,
                ticker=ticker,
                qty=qty,
                price=price,
                status=OrderStatus.EXECUTED,
                filled=qty,
                session=session
            )
        if remaining_qty > 0:
            info_logger.info(f"create PARTIALLY_EXECUTED order")
            await balance_crud.release_ticker(user_id, ticker=ticker, amount=remaining_qty, session=session)
            return await self._create_order(
                user_id=user_id,
                direction=OrderDirection.SELL,
                ticker=ticker,
                qty=qty,
                price=price,
                status=OrderStatus.PARTIALLY_EXECUTED,
                filled=remaining_qty,
                session=session
            )

    async def _get_sell_orders(
            self,
            ticker: str,
            user_id: str,
            session: AsyncSession) -> Sequence[Order]:
        """
        Поиск подходящих встречных заявок

        Args:
            ticker: тикер инструмента
            session: сессия БД

        Returns:
            Список найденных заявок
        """
        stmt = (
            select(Order)
            .where(
                and_(
                    Order.ticker == ticker,
                    Order.direction == OrderDirection.SELL,
                    or_(
                        Order.status == OrderStatus.NEW,
                        Order.status == OrderStatus.PARTIALLY_EXECUTED
                    ),
                    Order.user_id != user_id
                )
            )
            .order_by(asc(Order.price), asc(Order.created_at)))

        result = await session.execute(stmt)
        return result.scalars().all()

    async def _get_sell_orders_by_price(
            self,
            ticker: str,
            price: int,
            user_id: str,
            session: AsyncSession) -> Sequence[Order]:
        """
        Поиск подходящих встречных заявок

        Args:
            ticker: тикер инструмента
            session: сессия БД

        Returns:
            Список найденных заявок
        """
        stmt = (
            select(Order)
            .where(
                and_(
                    Order.ticker == ticker,
                    Order.direction == OrderDirection.SELL,
                    or_(
                        Order.status == OrderStatus.NEW,
                        Order.status == OrderStatus.PARTIALLY_EXECUTED
                    ),
                    Order.price <= price,
                    Order.user_id != user_id
                )
            )
            .order_by(asc(Order.price), asc(Order.created_at)))

        result = await session.execute(stmt)
        return result.scalars().all()

    async def _get_buy_orders(
            self,
            ticker: str,
            user_id: str,
            session: AsyncSession) -> Sequence[Order]:
        """
        Поиск подходящих встречных заявок

        Args:
            ticker: тикер инструмента
            session: сессия БД

        Returns:
            Список найденных заявок
        """
        stmt = (
            select(Order)
            .where(
                and_(
                    Order.ticker == ticker,
                    Order.direction == OrderDirection.BUY,
                    or_(
                        Order.status == OrderStatus.NEW,
                        Order.status == OrderStatus.PARTIALLY_EXECUTED
                    ),
                    Order.user_id != user_id
                )
            )
            .order_by(desc(Order.price), asc(Order.created_at)))

        result = await session.execute(stmt)
        return result.scalars().all()

    async def _get_buy_orders_by_price(
            self,
            ticker: str,
            price: int,
            user_id: str,
            session: AsyncSession) -> Sequence[Order]:
        """
        Поиск подходящих встречных заявок

        Args:
            ticker: тикер инструмента
            session: сессия БД

        Returns:
            Список найденных заявок
        """
        stmt = (
            select(Order)
            .where(
                and_(
                    Order.ticker == ticker,
                    Order.direction == OrderDirection.BUY,
                    or_(
                        Order.status == OrderStatus.NEW,
                        Order.status == OrderStatus.PARTIALLY_EXECUTED
                    ),
                    Order.price >= price,
                    Order.user_id != user_id
                )
            )
            .order_by(desc(Order.price), asc(Order.created_at)))

        result = await session.execute(stmt)
        return result.scalars().all()

    async def _try_fill(
            self,
            order_id: str,
            max_amount: int,
            max_price: int,
            session: AsyncSession) -> int:
        try:
            order = (await session.execute(
                select(self.model)
                .where(and_(self.model.id == order_id,
                            or_(self.model.status == OrderStatus.NEW,
                                self.model.status == OrderStatus.PARTIALLY_EXECUTED)))
                .with_for_update()
            )).scalar_one_or_none()

            if not order:
                info_logger.info(f"not order:{order_id}")
                return 0

            info_logger.info(f"try fill order:{order.__dict__}")
            ostatok = order.qty - order.filled
            block = min(ostatok, max_amount)
            info_logger.info(f"block without price:{block}")

            while block * order.price > max_price:
                block -= 1
            info_logger.info(f"block with price:{block}")
            if block <= 0:
                return 0

            if ostatok - block == 0:
                (await session.execute(
                    update(self.model)
                    .where(and_(self.model.id == order.id))
                    .values(filled=self.model.filled + block, status=OrderStatus.EXECUTED)
                    .returning(self.model)
                )).scalar_one()
            else:
                (await session.execute(
                    update(self.model)
                    .where(and_(self.model.id == order.id))
                    .values(filled=self.model.filled + block, status=OrderStatus.PARTIALLY_EXECUTED)
                    .returning(self.model)
                )).scalar_one()

            await session.commit()
            return block
        except IntegrityError as e:
            await session.rollback()
            return 0

    async def _release_fill(
            self,
            order_id: str,
            qty: int,
            session: AsyncSession):
        try:
            order = (await session.execute(
                update(self.model)
                .where(and_(self.model.id == order_id))
                .values(filled=self.model.filled - qty)
                .returning(self.model)
            )).scalar_one()
            if order.status != OrderStatus.CANCELLED:
                order.status = OrderStatus.PARTIALLY_EXECUTED

            await session.commit()
        except IntegrityError as e:
            await session.rollback()
            raise e

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
        error_logger.error(f"orderId 2: {str(order.id)}")
        return order


order_crud_v2 = CRUDOrderV2()
