from enum import Enum, StrEnum, auto


class UserRole(StrEnum):
    ADMIN = auto()
    USER = auto()


class CurrencyTicker(str, Enum):
    RUB = 'RUB'
