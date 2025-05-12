from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OkResponse(BaseModel):
    success: Literal[True] = Field(default=True)
    model_config = ConfigDict(from_attributes=True)


class TickerBase(BaseModel):
    ticker: str = Field(
        ...,
        pattern=r'^[A-Z]{2,10}$',
        description='Ticker must be 2-10 uppercase letters',
    )
