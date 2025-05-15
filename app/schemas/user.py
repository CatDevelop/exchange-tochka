from pydantic import BaseModel, constr

from app.core.enums import UserRole


class NewUser(BaseModel):
    name: constr(min_length=3)


class User(BaseModel):
    id: str
    name: str
    role: UserRole
    api_key: str

    class Config:
        from_attributes = True
