from enum import StrEnum, auto, Enum


class UserRole(StrEnum):
    ADMIN = auto()
    USER = auto()

class CurrencyTicker(str, Enum):
    RUB = "RUB"