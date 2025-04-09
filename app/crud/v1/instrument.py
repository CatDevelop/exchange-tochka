from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.instrument import Instrument
from app.schemas.instrument import InstrumentCreate, InstrumentResponse


class CRUDInstrument(CRUDBase[Instrument]):
    async def get_all(self, async_session: AsyncSession) -> list[InstrumentResponse]:
        instruments = self.get_multi(async_session)
        return [
            InstrumentResponse.model_validate(instrument) for instrument in instruments
        ]

    async def create_instrument(
        self, obj_in: InstrumentCreate, async_session: AsyncSession
    ) -> InstrumentResponse:
        existing_instrument = await self.get_by_attribute(
            'ticker', obj_in.ticker, async_session
        )
        if existing_instrument:
            raise ValueError('Instrument with this ticker already exists')

        instrument = await self.create(obj_in, async_session)
        return InstrumentResponse.model_validate(instrument)


instrument_crud = CRUDInstrument(Instrument)
