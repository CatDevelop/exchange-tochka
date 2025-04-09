from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.current_user import is_user_admin
from app.core.db import get_async_session
from app.crud.v1.instrument import instrument_crud
from app.schemas.instrument import InstrumentCreate, InstrumentResponse

router = APIRouter(prefix='', tags=['instrument', 'admin'])


@router.post(
    '/admin/instrument',
    response_model=InstrumentResponse,
    summary='Создать инструмент',
    dependencies=[Depends(is_user_admin)],
    responses={
        409: {'description': 'Инструмент уже существует'},
        422: {'description': 'Ошибка валидации данных'},
        500: {'description': 'Внутренняя ошибка сервера'},
    },
    tags=['admin'],
)
async def add_instrument(
    obj_in: InstrumentCreate, session: AsyncSession = Depends(get_async_session)
):
    try:
        instrument = await instrument_crud.create_instrument(obj_in, session)
        return instrument
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except HTTPException as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail='Internal server error')
