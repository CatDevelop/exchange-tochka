from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_async_session
from app.crud.v1.instrument import instrument_crud
from app.schemas.instrument import InstrumentResponse

router = APIRouter(prefix='', tags=['public'])


@router.get(
    '/public/instrument',
    response_model=List[InstrumentResponse],
    summary='Список доступных инструментов',
    responses={500: {'description': 'Внутренняя ошибка сервера'}},
)
async def list_instruments(session: AsyncSession = Depends(get_async_session)):
    try:
        instruments = await instrument_crud.get_all(session)
        return instruments
    except Exception:
        raise HTTPException(status_code=500, detail='Internal server error')
