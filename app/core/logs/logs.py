import logging.config
import logging.handlers
from functools import wraps
from typing import Any, Awaitable, Callable, TypeVar, cast

from app.core.logs.config import LOGGING_CONFIG_RESULT

logging.config.dictConfig(LOGGING_CONFIG_RESULT)

debug_logger = logging.getLogger('default_debug_logger')
info_logger = logging.getLogger('default_info_logger')
error_logger = logging.getLogger('default_error_logger')


F = TypeVar('F', bound=Callable[..., Awaitable[Any]])


def error_log(func: F) -> F:
    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            error_logger.error(
                f"Can't do this operation in DB "
                f"in method {func.__name__}. Error: {e}"
            )
            raise e

    return cast(F, wrapper)


T = TypeVar('T', bound=Callable[..., Any])


def no_log() -> Callable[[T], T]:
    def decorator(func: T) -> T:
        setattr(func, '_no_log', True)
        return func

    return decorator
