from typing import Any, Generic, Sequence, Type, TypeVar

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from sqlalchemy import ColumnElement, select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import Base
from app.core.logs.logs import error_log, error_logger, info_logger

PydanticSchema = TypeVar('PydanticSchema', bound=BaseModel)
SQLAlchemyModel = TypeVar('SQLAlchemyModel', bound=Base)


class CRUDBase(Generic[SQLAlchemyModel]):
    def __init__(self, model: Type[SQLAlchemyModel], primary_key_name: str) -> None:
        self.model = model
        self.primary_key_name = primary_key_name

    def get_primary_key_value(self, db_obj: SQLAlchemyModel) -> Any:
        """Извлекает значение первичного ключа из объекта.

        Args:
            db_obj (SQLAlchemyModel): Объект, из которого нужно извлечь значение
            первичного ключа.

        Returns:
            Any: Значение первичного ключа.
        """
        return getattr(db_obj, self.primary_key_name)

    @error_log
    async def get(
        self,
        primary_key_value: Any,
        async_session: AsyncSession,
    ) -> SQLAlchemyModel | None:
        """Получает один элемент по его первичному ключу.

        Args:
            primary_key_value (Any): ИД объекта
            async_session (AsyncSession): Асинхронная сессия

        Returns:
            SQLAlchemyModel | None: Найденный объект или None, если объект не найден
        """
        db_obj = await async_session.execute(
            select(self.model).where(
                getattr(self.model, self.primary_key_name) == primary_key_value
            )
        )
        info_logger.info(
            f"Get successfully object: {self.model.__name__}"
            f" with {self.primary_key_name}: {primary_key_value}"
        )
        return db_obj.scalars().first()

    @error_log
    async def get_multi(
        self,
        async_session: AsyncSession,
        order_by: tuple[ColumnElement[Any], ...] | None = None,
        **filter_by: Any,
    ) -> Sequence[SQLAlchemyModel]:
        """Получает список элементов.

        Args:
            async_session (AsyncSession): Асинхронная сессия
            order_by (tuple[ColumnElement, ...] | None, optional): Кортеж столбцов для
                сортировки. Используйте .asc() для сортировки по возрастанию и .desc()
                для убывания. По умолчанию None.
            **filter_by (Any): Именованные аргументы для фильтрации в формате
                поле=значение

        Returns:
            list[SQLAlchemyModel]: Список найденных объектов или [], если объекты не
                найдены

        Example:
        ```
            # Сортировка по одному полю по возрастанию
            await crud.get_multi(
                session,
                order_by=(User.created_at.asc(),)
            )

            # Сортировка по нескольким полям
            await crud.get_multi(
                session,
                order_by=(User.role.asc(), User.created_at.desc())
            )

            # Сортировка с фильтрацией
            await crud.get_multi(
                session,
                order_by=(User.created_at.desc(),),
                is_active=True,
                role='admin'
            )
        ```
        """
        query = select(self.model).filter_by(**filter_by)
        if order_by:
            query = query.order_by(*order_by)
        db_objs = await async_session.execute(query)
        info_logger.info(
            f"Get successfully objects {self.model.__name__}" f" in get_multi"
        )
        return db_objs.scalars().unique().all()

    @error_log
    async def create(
        self,
        obj_in: PydanticSchema,
        async_session: AsyncSession,
        user_id: int | None = None,
    ) -> SQLAlchemyModel:
        """Создает новый объект.

        Args:
            obj_in (PydanticSchema): Pydantic объект, который будет создан.
            async_session (AsyncSession): Асинхронная сессия
            user_id (int | None, optional): ИД пользователя, к которому будет привязан
                объект. По умолчанию None.

        Returns:
            SQLAlchemyModel: Созданный объект
        """
        obj_in_data = obj_in.model_dump()
        if user_id is not None:
            obj_in_data['user_id'] = user_id
        db_obj = self.model(**obj_in_data)
        async_session.add(db_obj)
        await async_session.flush()
        await async_session.refresh(db_obj)
        info_logger.info(
            f"Create new obj: {self.model.__name__}"
            f" with {self.primary_key_name}: {self.get_primary_key_value(db_obj)}"
        )
        return db_obj

    @error_log
    async def update(
        self,
        db_obj: SQLAlchemyModel,
        obj_in: PydanticSchema,
        async_session: AsyncSession,
    ) -> SQLAlchemyModel:
        """Обновляет объект.

        Args:
            db_obj (SQLAlchemyModel): Объект из БД, который будет обновлен.
            obj_in (PydanticSchema): Pydantic объект, что будем обновлять.
            async_session (AsyncSession): Асинхронная сессия

        Returns:
            SQLAlchemyModel: Обновленный объект
        """
        obj_data = jsonable_encoder(db_obj)
        update_data = obj_in.model_dump(exclude_unset=True)

        for field in update_data:
            if field in obj_data:
                setattr(db_obj, field, update_data[field])
        async_session.add(db_obj)
        await async_session.flush()
        await async_session.refresh(db_obj)
        info_logger.info(
            f"Update obj: {self.model.__name__}"
            f" with {self.primary_key_name}: {self.get_primary_key_value(db_obj)}"
        )
        return db_obj

    @error_log
    async def delete(
        self,
        db_obj: SQLAlchemyModel,
        async_session: AsyncSession,
    ) -> None:
        """Удаляет объект.

        Args:
            db_obj (SQLAlchemyModel): Объект из БД, который будет удален.
            async_session (AsyncSession): Асинхронная сессия
        """
        await async_session.delete(db_obj)
        await async_session.flush()
        info_logger.info(
            f"Successfully remove obj:"
            f" {self.model.__name__} with {self.primary_key_name}: "
            f"{self.get_primary_key_value(db_obj)}"
        )

    async def get_by_attribute(
        self,
        attr_name: str,
        attr_value: Any,
        async_session: AsyncSession,
    ) -> SQLAlchemyModel | None:
        """Получает объект по атрибуту.

        Args:
            attr_name (str): Имя аттрибута, по которому будет происходить поиск
            attr_value (Any): Значение атрибута, по которому будет происходить поиск
            async_session (AsyncSession): Асинхронная сессия

        Raises:
            AttributeError: Если атрибута нет в модели
            ValueError: Если невозможно выполнить запрос

        Returns:
            SQLAlchemyModel | None: Найденный объект или None, если объект не найден
        """
        if not hasattr(self.model, attr_name):
            error_logger.error(
                f"Attribute '{attr_name}' doesn't exist in the model"
                f" {self.model.__name__}"
            )
            raise AttributeError(
                f"Атрибут '{attr_name}' не существует в модели {self.model.__name__}"
            )

        try:
            attr = getattr(self.model, attr_name)
            db_obj = await async_session.execute(
                select(self.model).where(attr == attr_value)
            )
            info_logger.info(
                f"Successfully get object {self.model.__name__}" f" in get_by_attribute"
            )
            return db_obj.scalars().first()
        except InvalidRequestError as e:
            error_logger.error(
                f"Can't make request with attribute: '{attr_name}':" f" {str(e)}"
            )
            raise ValueError(
                f"Невозможно выполнить запрос с атрибутом '{attr_name}': {str(e)}"
            )
