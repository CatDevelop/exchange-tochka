from app.schemas.base import TickerBase


class InstrumentResponse(TickerBase):
    name: str

    class Config:
        from_attributes = True


class InstrumentCreate(TickerBase):
    name: str

    class Config:
        from_attributes = True


class InstrumentDelete(TickerBase):
    pass
