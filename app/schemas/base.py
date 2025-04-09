from typing import Literal

from pydantic import BaseModel, Field


class OkResponse(BaseModel):
    success: Literal[True] = True


class TickerBase(BaseModel):
    ticker: str = Field(
        ...,
        pattern=r'^[A-Z]{2,10}$',
        description='Ticker must be 2-10 uppercase letters',
    )
