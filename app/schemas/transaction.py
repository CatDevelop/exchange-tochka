from datetime import datetime
from typing import List

from pydantic import BaseModel, Field


class TransactionResponse(BaseModel):
    """Схема для ответа с одной транзакцией"""
    ticker: str = Field(..., description="Тикер инструмента")
    amount: int = Field(..., description="Количество")
    price: int = Field(..., description="Цена")
    timestamp: datetime = Field(..., description="Время транзакции")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "ticker": "MEMECOIN",
                "amount": 10,
                "price": 100,
                "timestamp": "2025-05-16T12:59:42.978Z"
            }
        }


class TransactionListResponse(BaseModel):
    """Схема для списка транзакций"""
    transactions: List[TransactionResponse] = Field(
        default_factory=list, description="Список транзакций"
    )

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "transactions": [
                    {
                        "ticker": "MEMECOIN",
                        "amount": 10,
                        "price": 100,
                        "timestamp": "2025-05-16T12:59:42.978Z"
                    },
                    {
                        "ticker": "MEMECOIN",
                        "amount": 5,
                        "price": 105,
                        "timestamp": "2025-05-16T12:58:30.123Z"
                    }
                ]
            }
        } 