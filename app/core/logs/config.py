from typing import Any

from deepmerge import always_merger

MAX_BYTES = 1024 * 1024 * 100
FILENAME = '/tmp/giga_logs.log'
INFO_FILENAME = '/tmp/info_logs.log'
DEBUG_FILENAME = '/tmp/debug_logs.log'
ERROR_FILENAME = '/tmp/error_logs.log'

# Конфигурация Elasticsearch
ES_HOST = '192.168.1.219'
ES_PORT = 9200
ES_INDEX_PREFIX = 'exchange_logs'

LOGGING_CONFIG_BASE: dict[str, Any] = {
    'version': 1,
    'disable_existing_loggers': False,
}

# Конфигурация для Elasticsearch
LOGGING_CONFIG_ELASTICSEARCH: dict[str, Any] = {
    'formatters': {
        'es_formatter': {
            'format': '%(asctime)s.%(msecs)03d %(module)s:%(lineno)d [%(levelname)s] - %(message)s',
            'datefmt': '[%Y-%m-%d %H:%M:%S]',
            'class': 'logging.Formatter',
        },
    },
    'handlers': {
        'elasticsearch_handler': {
            'class': 'app.core.logs.elasticsearch.ESHandler',
            'hosts': [f'{ES_HOST}:{ES_PORT}'],
            'es_index_name': f'{ES_INDEX_PREFIX}-all',
            'level': 'DEBUG',
            'formatter': 'es_formatter',
        },
        'elasticsearch_debug_handler': {
            'class': 'app.core.logs.elasticsearch.ESHandler',
            'hosts': [f'{ES_HOST}:{ES_PORT}'],
            'es_index_name': f'{ES_INDEX_PREFIX}-debug',
            'level': 'DEBUG',
            'formatter': 'es_formatter',
        },
        'elasticsearch_info_handler': {
            'class': 'app.core.logs.elasticsearch.ESHandler',
            'hosts': [f'{ES_HOST}:{ES_PORT}'],
            'es_index_name': f'{ES_INDEX_PREFIX}-info',
            'level': 'INFO',
            'formatter': 'es_formatter',
        },
        'elasticsearch_error_handler': {
            'class': 'app.core.logs.elasticsearch.ESHandler',
            'hosts': [f'{ES_HOST}:{ES_PORT}'],
            'es_index_name': f'{ES_INDEX_PREFIX}-error',
            'level': 'ERROR',
            'formatter': 'es_formatter',
        },
    },
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

LOGGING_CONFIG_ROOT: dict[str, Any] = {
    'handlers': {
        'elasticsearch_root_handler': {
            'class': 'app.core.logs.elasticsearch.ESHandler',
            'hosts': [f'{ES_HOST}:{ES_PORT}'],
            'es_index_name': f'{ES_INDEX_PREFIX}-python',
            'level': 'INFO',
            'formatter': 'es_formatter',
        },
    },
    'root': {
        'handlers': ['elasticsearch_root_handler'],
        'level': 'INFO',
    },
}

LOGGING_CONFIGS = [
    LOGGING_CONFIG_BASE,
    LOGGING_CONFIG_DEBUG,
    LOGGING_CONFIG_INFO,
    LOGGING_CONFIG_ERROR,
    LOGGING_CONFIG_UVICORN,
    LOGGING_CONFIG_GUNICORN,
]

LOGGING_CONFIG_RESULT: dict[str, Any] = {}
for config in LOGGING_CONFIGS:
    LOGGING_CONFIG_RESULT = always_merger.merge(LOGGING_CONFIG_RESULT, config)