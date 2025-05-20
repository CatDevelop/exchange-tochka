import logging.config
import os
import threading
import time

# Импортируем только конфигурацию
from app.core.logs.config import LOGGING_CONFIG_RESULT

# Настраиваем базовую конфигурацию логирования
logging.config.dictConfig(LOGGING_CONFIG_RESULT)

# Импортируем логгеры
from app.core.logs.logs import debug_logger, info_logger, error_logger, error_log, no_log

# Чтобы избежать циклических импортов, настраиваем Elasticsearch только после базовой настройки логгеров
# Используем отложенный импорт и настройку
def setup_elastic(max_retries=3, retry_interval=5):
    """
    Настраивает логирование в Elasticsearch с повторными попытками
    
    Args:
        max_retries: Максимальное количество попыток подключения
        retry_interval: Интервал между попытками в секундах
    """
    logger = logging.getLogger('startup')
    
    for attempt in range(max_retries):
        try:
            from app.core.logs.elastic_setup import setup_elasticsearch_logging
            success = setup_elasticsearch_logging()
            
            if success:
                logger.info("Elasticsearch логирование успешно настроено")
                return
            else:
                logger.warning(f"Не удалось настроить Elasticsearch логирование (попытка {attempt+1}/{max_retries})")
        except Exception as e:
            logger.error(f"Ошибка при настройке Elasticsearch логирования: {e} (попытка {attempt+1}/{max_retries})")
        
        # Если это не последняя попытка, ждем перед следующей
        if attempt < max_retries - 1:
            time.sleep(retry_interval)
    
    logger.error(f"Не удалось настроить Elasticsearch логирование после {max_retries} попыток. Продолжаем работу без Elasticsearch.")

# Запускаем настройку Elasticsearch асинхронно с повторными попытками
threading.Thread(target=setup_elastic, daemon=True).start()

__all__ = ["debug_logger", "info_logger", "error_logger", "error_log", "no_log"] 