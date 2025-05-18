import logging
from app.core.logs.config import ES_HOST, ES_PORT, ES_INDEX_PREFIX
from app.core.logs.elasticsearch import ESHandler, setup_elasticsearch_index_template


def setup_elasticsearch_logging():
    """
    Настраивает логирование в Elasticsearch после базовой настройки логгеров.
    Подключается к существующим логгерам для отправки логов в Elasticsearch.
    """
    # Формируем правильный URL с протоколом
    es_host_url = f"http://{ES_HOST}:{ES_PORT}"
    print(f"Пытаемся подключиться к Elasticsearch по адресу: {es_host_url}")
    
    # Создаем шаблон индекса
    try:
        setup_elasticsearch_index_template(
            es_host=es_host_url,
            template_name='exchange-logs-template',
            index_pattern='exchange_logs-*'
        )
    except Exception as e:
        logging.getLogger('elasticsearch_setup').error(
            f"Не удалось настроить шаблон индекса Elasticsearch: {e}"
        )
        return False
    
    try:
        # Создаем базовые обработчики для различных уровней логирования
        es_formatter = logging.Formatter(
            '%(asctime)s.%(msecs)03d %(module)s:%(lineno)d [%(levelname)s] - %(message)s',
            datefmt='[%Y-%m-%d %H:%M:%S]'
        )
        
        # Используем один URL вместо списка, чтобы избежать проблем с форматированием
        es_host = es_host_url
        
        # Debug logger
        es_debug_handler = ESHandler(
            es_host=es_host,
            es_index_name=f"{ES_INDEX_PREFIX}-debug",
            level=logging.DEBUG
        )
        es_debug_handler.setFormatter(es_formatter)
        logging.getLogger('default_debug_logger').addHandler(es_debug_handler)
        
        # Info logger
        es_info_handler = ESHandler(
            es_host=es_host,
            es_index_name=f"{ES_INDEX_PREFIX}-info",
            level=logging.INFO
        )
        es_info_handler.setFormatter(es_formatter)
        logging.getLogger('default_info_logger').addHandler(es_info_handler)
        
        # Error logger
        es_error_handler = ESHandler(
            es_host=es_host,
            es_index_name=f"{ES_INDEX_PREFIX}-error",
            level=logging.ERROR
        )
        es_error_handler.setFormatter(es_formatter)
        logging.getLogger('default_error_logger').addHandler(es_error_handler)
        
        # Uvicorn и Gunicorn логгеры
        es_general_handler = ESHandler(
            es_host=es_host,
            es_index_name=f"{ES_INDEX_PREFIX}-all",
            level=logging.INFO
        )
        es_general_handler.setFormatter(es_formatter)
        
        # Добавляем обработчик к uvicorn логгерам
        uvicorn_logger = logging.getLogger('uvicorn')
        if uvicorn_logger:
            uvicorn_logger.addHandler(es_general_handler)
            
        uvicorn_access = logging.getLogger('uvicorn.access')
        if uvicorn_access:
            uvicorn_access.addHandler(es_general_handler)
        
        # Добавляем обработчик к gunicorn логгерам
        gunicorn_error = logging.getLogger('gunicorn.error')
        if gunicorn_error:
            gunicorn_error.addHandler(es_general_handler)
            
        gunicorn_access = logging.getLogger('gunicorn.access')
        if gunicorn_access:
            gunicorn_access.addHandler(es_general_handler)
            
        # Корневой логгер
        root_handler = ESHandler(
            es_host=es_host,
            es_index_name=f"{ES_INDEX_PREFIX}-python",
            level=logging.INFO
        )
        root_handler.setFormatter(es_formatter)
        logging.getLogger().addHandler(root_handler)
        
        print(f"Elasticsearch логирование успешно настроено на {es_host}")
        return True
    except Exception as e:
        logging.getLogger('elasticsearch_setup').error(
            f"Ошибка при настройке обработчиков Elasticsearch: {e}"
        )
        return False 