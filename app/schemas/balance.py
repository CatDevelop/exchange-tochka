from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, RootModel


class DepositRequest(BaseModel):
    user_id: UUID = Field(..., description='UUID пользователя')
    ticker: str = Field(..., description='Тикер валюты')
    amount: int = Field(..., gt=0, description='Сумма пополнения (должна быть > 0)')
    model_config = ConfigDict(from_attributes=True)


class WithdrawRequest(BaseModel):
    user_id: UUID = Field(..., description='UUID пользователя')
    ticker: str = Field(..., description='Тикер валюты')
    amount: int = Field(..., gt=0, description='Сумма списания (должна быть > 0)')
    model_config = ConfigDict(from_attributes=True)


class BalanceResponse(RootModel[dict[str, int]]):
    pass
