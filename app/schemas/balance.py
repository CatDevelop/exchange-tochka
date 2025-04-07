import uuid
from decimal import Decimal

from pydantic.v1 import BaseModel, Field, validator


class BalanceOperationBase(BaseModel):
    user_id: uuid.UUID = Field(..., description="UUID пользователя")
    ticker: str = Field(..., description="Тикер валюты")
    amount: Decimal = Field(..., gt=0, description="Сумма операции (должна быть больше 0)")

    @validator('amount')
    def validate_amount(cls, v):
        if v <= Decimal('0'):
            raise ValueError("Сумма должна быть положительной")
        return v


class DepositRequest(BalanceOperationBase):
    pass


class WithdrawRequest(BalanceOperationBase):
    pass
