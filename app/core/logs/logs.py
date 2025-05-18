import logging.config
import logging.handlers
from functools import wraps
from typing import Any, Awaitable, Callable, TypeVar, cast

# Импортируем конфигурацию, но применяем её позже
from app.core.logs.config import LOGGING_CONFIG_RESULT

# Настройка базовых логгеров
debug_logger = logging.getLogger('default_debug_logger')
info_logger = logging.getLogger('default_info_logger')
error_logger = logging.getLogger('default_error_logger')

# Применяем конфигурацию логирования
try:
    logging.config.dictConfig(LOGGING_CONFIG_RESULT)
    print("Логгирование с Elasticsearch успешно инициализировано")
except Exception as e:
    print(f"Ошибка инициализации логгирования: {e}")
    
    # Настраиваем аварийный handler для вывода в консоль
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    
    # Добавляем хендлер к логгерам
    debug_logger.addHandler(console_handler)
    info_logger.addHandler(console_handler)
    error_logger.addHandler(console_handler)
    
    # Устанавливаем уровни логирования
    debug_logger.setLevel(logging.DEBUG)
    info_logger.setLevel(logging.INFO)
    error_logger.setLevel(logging.ERROR)


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
