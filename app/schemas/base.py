from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OkResponse(BaseModel):
    success: Literal[True] = Field(default=True)
    model_config = ConfigDict(from_attributes=True)
