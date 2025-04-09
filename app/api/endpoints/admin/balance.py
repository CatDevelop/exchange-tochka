from typing import Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.current_user import get_current_user, is_user_admin
from app.core.db import get_async_session
from app.crud.v1.balance import balance_crud
from app.models import User
from app.schemas.balance import BalanceResponse, DepositRequest, WithdrawRequest
from app.schemas.base import OkResponse

router = APIRouter()


@router.get(
    '/balance',
    response_model=BalanceResponse,
    summary='Get Balances',
    responses={
        200: {
            'description': 'Successful Response',
            'content': {
                'application/json': {'example': {'MEMCOIN': 0, 'DODGE': 100500}}
            },
        },
        401: {'description': 'Unauthorized'},
    },
)
async def get_balances(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> Dict[str, int]:
    """
    Получение балансов текущего пользователя.

    Возвращает словарь, где ключи - тикеры валют, значения - целочисленные суммы.
    """
    try:
        balances = await balance_crud.get_user_balances(
            user_id=current_user.id, async_session=session
        )
        return balances
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post(
    '/admin/balance/deposit',
    response_model=OkResponse,
    dependencies=[Depends(is_user_admin)],
    responses={
        422: {'description': 'Ошибка валидации данных'},
        500: {'description': 'Внутренняя ошибка сервера'},
    },
)
async def deposit_to_balance(
    body: DepositRequest,
    session: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> OkResponse:
    try:
        await balance_crud.deposit(
            user_id=body.user_id,
            ticker=body.ticker,
            amount=body.amount,
            async_session=session,
        )
        return OkResponse()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail='Internal server error')


@router.post(
    '/admin/balance/withdraw',
    response_model=OkResponse,
    dependencies=[Depends(is_user_admin)],
    responses={
        422: {'description': 'Ошибка валидации данных'},
        500: {'description': 'Внутренняя ошибка сервера'},
    },
)
async def withdraw_from_balance(
    body: WithdrawRequest,
    session: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> OkResponse:
    try:
        await balance_crud.withdraw(
            user_id=body.user_id,
            ticker=body.ticker,
            amount=body.amount,
            async_session=session,
        )
        return OkResponse()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail='Internal server error')
