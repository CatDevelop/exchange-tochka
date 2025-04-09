from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.instrument import Instrument
from app.schemas.instrument import InstrumentResponse


class CRUDInstrument(CRUDBase[Instrument]):
    async def get_all(self, async_session: AsyncSession) -> list[InstrumentResponse]:
        instruments = self.get_multi(async_session)
        return [
            InstrumentResponse.model_validate(instrument) for instrument in instruments
        ]


instrument_crud = CRUDInstrument(Instrument)
