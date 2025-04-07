from pydantic import BaseModel, Field


class OkResponse(BaseModel):
    success: bool = Field(True, const=True)
