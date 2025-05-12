from pydantic import BaseModel

from app.core.enums import UserRole


class UserRegister(BaseModel):
    name: str


class UserResponse(BaseModel):
    name: str
    role: UserRole
    api_key: str

    class Config:
        from_attributes = True
