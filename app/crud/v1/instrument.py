from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logs.logs import error_log
from app.crud.base import CRUDBase
from app.models.instrument import Instrument
from app.schemas.instrument import (
    InstrumentCreate,
    InstrumentDelete,
    InstrumentResponse,
)


class CRUDInstrument(CRUDBase[Instrument]):
    @error_log
    async def get_all(self, async_session: AsyncSession) -> list[InstrumentResponse]:
        """Получает все существующие инструменты"""
        instruments = self.get_multi(async_session)
        return [
            InstrumentResponse.model_validate(instrument) for instrument in instruments
        ]

    @error_log
    async def create_instrument(
        self, obj_in: InstrumentCreate, async_session: AsyncSession
    ) -> InstrumentResponse:
        """Создает новый инструмент"""
        existing_instrument = await self.get_by_attribute(
            'ticker', obj_in.ticker, async_session
        )
        if existing_instrument:
            raise ValueError(f'Instrument {obj_in.ticker} already exists')

        instrument = await self.create(obj_in, async_session)
        return InstrumentResponse.model_validate(instrument)

    @error_log
    async def delete_instrument(
        self, ticker: InstrumentDelete, async_session: AsyncSession
    ) -> None:
        """Удаляет существующий инструмент"""
        instrument = await instrument_crud.get_by_attribute(
            'ticker', ticker, async_session
        )
        if not instrument:
            raise ValueError(f"Instrument {ticker} not found")
        await self.delete(instrument, async_session)


instrument_crud = CRUDInstrument(Instrument)
