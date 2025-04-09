from pydantic import BaseModel


class InstrumentResponse(BaseModel):
    ticker: str
    name: str

    class Config:
        from_attributes = True


class InstrumentCreate(BaseModel):
    ticker: str
    name: str

    class Config:
        from_attributes = True
