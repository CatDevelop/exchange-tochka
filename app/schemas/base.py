from pydantic import BaseModel, Field


class OkResponse(BaseModel):
    success: bool = Field(True, const=True)


class TickerBase(BaseModel):
    ticker: str = Field(
        ..., regex=r'^[A-Z]{2,10}$', description='Ticker must be 2-10 uppercase letters'
    )
