from typing import Any
import os

from deepmerge import always_merger
from app.core.logs.elasticsearch_logger import get_elasticsearch_config

MAX_BYTES = 1024 * 1024 * 100
FILENAME = '/tmp/giga_logs.log'
INFO_FILENAME = '/tmp/info_logs.log'
DEBUG_FILENAME = '/tmp/debug_logs.log'
ERROR_FILENAME = '/tmp/error_logs.log'

# Получаем URL Elasticsearch из переменной окружения или используем значение по умолчанию
ELASTICSEARCH_HOST = os.environ.get('ELASTICSEARCH_HOST', 'http://elasticsearch:9200')

LOGGING_CONFIG_BASE: dict[str, Any] = {
    'version': 1,
    'disable_existing_loggers': False,
}

LOGGING_CONFIG_UVICORN: dict[str, Any] = {
    'formatters': {
        'default_uvicorn_formatter': {
            '()': 'uvicorn.logging.DefaultFormatter',
            'fmt': '%(levelprefix)s %(message)s',
            'use_colors': None,
        },
        'access_uvicorn_formatter': {
            '()': 'uvicorn.logging.AccessFormatter',
            'fmt': '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',  # noqa: E501
        },
        'file_default_uvicorn_formatter': {
            '()': 'uvicorn.logging.DefaultFormatter',
            'fmt': '%(levelprefix)s %(message)s',
            'use_colors': False,
        },
        'file_access_uvicorn_formatter': {
            '()': 'uvicorn.logging.AccessFormatter',
            'fmt': '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',  # noqa: E501
            'use_colors': False,
        },
    },
    'handlers': {
        'default_uvicorn_handler': {
            'formatter': 'default_uvicorn_formatter',
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stderr',
        },
        'access_uvicorn_handler': {
            'formatter': 'access_uvicorn_formatter',
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stdout',
        },
        'file_default_uvicorn_handler': {
            'formatter': 'file_default_uvicorn_formatter',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': FILENAME,
            'maxBytes': MAX_BYTES,
            'mode': 'a',
            'encoding': 'utf-8',
            'level': 'INFO',
        },
        'file_access_uvicorn_handler': {
            'formatter': 'file_access_uvicorn_formatter',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': FILENAME,
            'maxBytes': MAX_BYTES,
            'mode': 'a',
            'encoding': 'utf-8',
            'level': 'INFO',
        },
    },
    'loggers': {
        'uvicorn': {
            'handlers': ['default_uvicorn_handler', 'file_default_uvicorn_handler'],
            'level': 'INFO',
            'propagate': False,
        },
        'uvicorn.error': {
            'level': 'INFO',
        },
        'uvicorn.access': {
            'handlers': ['access_uvicorn_handler', 'file_access_uvicorn_handler'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

LOGGING_CONFIG_GUNICORN: dict[str, Any] = {
    'formatters': {
        'generic_gunicorn_formatter': {
            'format': '%(asctime)s [%(process)d] [%(levelname)s] %(message)s',
            'datefmt': '[%Y-%m-%d %H:%M:%S %z]',
            'class': 'logging.Formatter',
        },
    },
    'handlers': {
        'console_gunicorn_handler': {
            'class': 'logging.StreamHandler',
            'formatter': 'generic_gunicorn_formatter',
            'stream': 'ext://sys.stdout',
        },
        'error_console_gunicorn_handler': {
            'class': 'logging.StreamHandler',
            'formatter': 'generic_gunicorn_formatter',
            'stream': 'ext://sys.stderr',
        },
        'file_gunicorn_handler': {
            'formatter': 'generic_gunicorn_formatter',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': FILENAME,
            'maxBytes': MAX_BYTES,
            'mode': 'a',
            'encoding': 'utf-8',
            'level': 'INFO',
        },
    },
    'loggers': {
        'gunicorn.error': {
            'level': 'INFO',
            'handlers': ['error_console_gunicorn_handler', 'file_gunicorn_handler'],
            'propagate': True,
            'qualname': 'gunicorn.error',
        },
        'gunicorn.access': {
            'level': 'INFO',
            'handlers': ['console_gunicorn_handler', 'file_gunicorn_handler'],
            'propagate': True,
            'qualname': 'gunicorn.access',
        },
    },
}

LOGGING_CONFIG_DEBUG: dict[str, Any] = {
    'formatters': {
        'default_debug_formatter': {
            'format': '%(asctime)s.%(msecs)03d %(module)s:%(lineno)d [%(levelname)s] - %(message)s',  # noqa: E501
            'datefmt': '[%Y-%m-%d %H:%M:%S]',
            'class': 'logging.Formatter',
        },
    },
    'handlers': {
        'console_debug_handler': {
            'formatter': 'default_debug_formatter',
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stdout',
            'level': 'DEBUG',
        },
        'file_debug_handler': {
            'formatter': 'default_debug_formatter',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': DEBUG_FILENAME,
            'maxBytes': MAX_BYTES,
            'mode': 'a',
            'encoding': 'utf-8',
            'level': 'DEBUG',
        },
    },
    'loggers': {
        'default_debug_logger': {
            'handlers': ['console_debug_handler', 'file_debug_handler'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}

LOGGING_CONFIG_INFO: dict[str, Any] = {
    'formatters': {
        'default_info_formatter': {
            'format': '%(asctime)s.%(msecs)03d %(module)s:%(lineno)d [%(levelname)s] - %(message)s',  # noqa: E501
            'datefmt': '[%Y-%m-%d %H:%M:%S]',
            'class': 'logging.Formatter',
        },
    },
    'handlers': {
        'console_info_handler': {
            'formatter': 'default_info_formatter',
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stdout',
            'level': 'INFO',
        },
        'file_info_handler': {
            'formatter': 'default_info_formatter',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': INFO_FILENAME,
            'maxBytes': MAX_BYTES,
            'mode': 'a',
            'encoding': 'utf-8',
            'level': 'INFO',
        },
    },
    'loggers': {
        'default_info_logger': {
            'handlers': ['console_info_handler', 'file_info_handler'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

LOGGING_CONFIG_ERROR: dict[str, Any] = {
    'formatters': {
        'default_error_formatter': {
            'format': '%(asctime)s.%(msecs)03d %(module)s:%(lineno)d [%(levelname)s] - %(message)s',  # noqa: E501
            'datefmt': '[%Y-%m-%d %H:%M:%S]',
            'class': 'logging.Formatter',
        },
    },
    'handlers': {
        'console_error_handler': {
            'formatter': 'default_error_formatter',
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stderr',
            'level': 'ERROR',
        },
        'file_error_handler': {
            'formatter': 'default_error_formatter',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': ERROR_FILENAME,
            'maxBytes': MAX_BYTES,
            'mode': 'a',
            'encoding': 'utf-8',
            'level': 'ERROR',
        },
    },
    'loggers': {
        'default_error_logger': {
            'handlers': ['console_error_handler', 'file_error_handler'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}

LOGGING_CONFIG_ELASTICSEARCH = get_elasticsearch_config(es_host=ELASTICSEARCH_HOST)

LOGGING_CONFIGS = [
    LOGGING_CONFIG_BASE,
    LOGGING_CONFIG_UVICORN,
    LOGGING_CONFIG_GUNICORN,
    LOGGING_CONFIG_DEBUG,
    LOGGING_CONFIG_INFO,
    LOGGING_CONFIG_ERROR,
    LOGGING_CONFIG_ELASTICSEARCH,
]

LOGGING_CONFIG_RESULT: dict[str, Any] = {}
for config in LOGGING_CONFIGS:
    LOGGING_CONFIG_RESULT = always_merger.merge(LOGGING_CONFIG_RESULT, config)

# Добавляем Elasticsearch handler ко всем логгерам
try:
    for logger_name, logger in LOGGING_CONFIG_RESULT['loggers'].items():
        if 'handlers' in logger and 'elasticsearch_handler' not in logger['handlers']:
            logger['handlers'].append('elasticsearch_handler')
except Exception as e:
    print(f"Ошибка при добавлении Elasticsearch handler к логгерам: {e}")
