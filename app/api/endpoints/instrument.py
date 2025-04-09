from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_async_session
from app.crud.v1.instrument import instrument_crud
from app.schemas.instrument import InstrumentResponse

router = APIRouter(prefix='', tags=['instrument'])


@router.get(
    '/public/instrument',
    response_model=List[InstrumentResponse],
    summary='Список доступных инструментов',
    tags=['public'],
)
async def list_instruments(session: AsyncSession = Depends(get_async_session)):
    instruments = await instrument_crud.get_all(session)
    return instruments
