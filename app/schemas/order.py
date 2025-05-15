from typing import Optional, List, Union
from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator

from app.models.order import OrderDirection, OrderStatus


class LimitOrderBody(BaseModel):
    direction: OrderDirection = Field(..., description="Направление заявки (BUY или SELL)")
    ticker: str = Field(..., description="Тикер валюты или инструмента")
    qty: int = Field(..., gt=0, description="Количество для покупки или продажи")
    price: Optional[int] = Field(None, gt=0,
                                 description="Цена для лимитной заявки. Если не передаётся, то используется рыночная заявка")

    class Config:
        schema_extra = {
            "example": {
                "direction": "BUY",
                "ticker": "USD",
                "qty": 1,
                "price": 45000
            }
        }


class MarketOrderBody(BaseModel):
    direction: OrderDirection = Field(..., description="Направление заявки (BUY или SELL)")
    ticker: str = Field(..., description="Тикер валюты или инструмента")
    qty: int = Field(..., gt=0, description="Количество для покупки или продажи")

    class Config:
        schema_extra = {
            "example": {
                "direction": "SELL",
                "ticker": "BTCUSD",
                "qty": 1
            }
        }


class OrderResponse(BaseModel):
    success: bool
    order_id: str


class CancelOrderResponse(BaseModel):
    success: bool
    order_id: str


class OrderBodyResponse(BaseModel):
    direction: OrderDirection
    ticker: str
    qty: int
    price: Optional[int] = None


class OrderDetailResponse(BaseModel):
    id: str
    status: OrderStatus
    user_id: str
    timestamp: datetime = Field(..., description="Время создания заявки")
    body: OrderBodyResponse
    filled: int = 0

    @field_validator('timestamp')
    @classmethod
    def ensure_timezone(cls, v: datetime) -> datetime:
        """Убедиться, что datetime содержит информацию о временной зоне"""
        if v.tzinfo is None:
            # Если временная зона не указана, используем UTC
            return v.replace(tzinfo=timezone.utc)
        return v


class Level(BaseModel):
    price: int = Field(..., description="Цена уровня")
    qty: int = Field(..., description="Количество на данном уровне")


class OrderbookResponse(BaseModel):
    bid_levels: List[Level] = Field(default_factory=list, description="Уровни спроса (покупки)")
    ask_levels: List[Level] = Field(default_factory=list, description="Уровни предложения (продажи)")