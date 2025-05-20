from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.current_user import is_user_admin
from app.core.db import get_async_session
from app.crud.v1.instrument import instrument_crud
from app.schemas.base import OkResponse
from app.schemas.instrument import (
    InstrumentCreate,
    InstrumentDelete,
    InstrumentResponse,
)

router = APIRouter(prefix='', tags=['admin'])


@router.post(
    '/admin/instrument',
    response_model=InstrumentResponse,
    summary='Создать инструмент',
    dependencies=[Depends(is_user_admin)],
    responses={
        409: {'description': 'The instrument already exists'},
    },
)
async def add_instrument(
    instrument: InstrumentCreate, session: AsyncSession = Depends(get_async_session)
):
    try:
        return await instrument_crud.create_instrument(instrument, session)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except HTTPException as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера: {str(e)}")


@router.delete(
    '/admin/instrument/{ticker}',
    response_model=OkResponse,
    summary='Удалить инструмент',
    dependencies=[Depends(is_user_admin)],
    responses={
        404: {'description': 'The instrument was not found'},
    },
)
async def delete_instrument(
    ticker: str, session: AsyncSession = Depends(get_async_session)
):
    try:
        instrument = InstrumentDelete(ticker=ticker)
        await instrument_crud.delete_instrument(instrument.ticker, session)
        return OkResponse()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера: {str(e)}")
