import logging
import datetime
import socket
import traceback
import time
from typing import Any, Dict, List, Optional, Union

from elasticsearch import Elasticsearch


def setup_elasticsearch_index_template(
    es_host: str,
    template_name: str = 'exchange-logs-template',
    index_pattern: str = 'exchange_logs-*'
) -> bool:
    """
    Создание шаблона индекса в Elasticsearch для корректного маппинга полей логов.
    
    Args:
        es_host: URL хоста Elasticsearch.
        template_name: Имя шаблона индекса.
        index_pattern: Паттерн индексов, к которым будет применен шаблон.
        
    Returns:
        bool: True в случае успеха, False в противном случае.
    """
    try:
        # Проверяем, содержит ли URL протокол
        if not es_host.startswith(('http://', 'https://')):
            es_host = f"http://{es_host}"
            
        # Создаем клиент с таймаутами
        es_client = Elasticsearch(
            [es_host],
            timeout=10,
            retry_on_timeout=True,
            max_retries=3
        )
        
        # Проверяем подключение
        if not es_client.ping():
            print(f"Не удалось подключиться к Elasticsearch по адресу {es_host}")
            return False
        
        # Шаблон индекса для Elasticsearch
        template_body = {
            "index_patterns": [index_pattern],
            "template": {
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0
                },
                "mappings": {
                    "properties": {
                        "timestamp": {"type": "date"},
                        "level": {"type": "keyword"},
                        "logger": {"type": "keyword"},
                        "module": {"type": "keyword"},
                        "funcName": {"type": "keyword"},
                        "lineNo": {"type": "integer"},
                        "message": {"type": "text"},
                        "host": {"type": "keyword"},
                        "host_ip": {"type": "ip"},
                        "exception": {
                            "properties": {
                                "type": {"type": "keyword"},
                                "message": {"type": "text"},
                                "traceback": {"type": "text"}
                            }
                        }
                    }
                }
            }
        }
        
        # Создание или обновление шаблона индекса
        es_client.indices.put_index_template(name=template_name, body=template_body)
        print(f"Шаблон индекса {template_name} успешно создан")
        return True
    except Exception as e:
        print(f"Ошибка при создании шаблона индекса: {e}")
        return False


class ESHandler(logging.Handler):
    """
    Обработчик логирования для отправки логов в Elasticsearch.
    """

    def __init__(
        self,
        es_host: str,
        es_index_name: str,
        auth_details: Optional[Dict[str, str]] = None,
        es_additional_fields: Optional[Dict[str, Any]] = None,
        level: int = logging.NOTSET,
        **kwargs: Any
    ):
        """
        Инициализация обработчика для Elasticsearch.

        Args:
            es_host: URL хоста Elasticsearch в формате 'http://host:port'.
            es_index_name: Имя индекса для логов (будет добавлен суффикс даты).
            auth_details: Информация для аутентификации (опционально).
            es_additional_fields: Дополнительные поля, которые будут добавлены к каждой записи.
            level: Уровень логирования.
            **kwargs: Дополнительные параметры для logging.Handler.
        """
        super().__init__(level=level, **kwargs)
        
        self.es_host = es_host
        self.es_index_name = es_index_name.lower()
        self.auth_details = auth_details
        self.es_additional_fields = es_additional_fields or {}
        
        # Добавляем информацию о хосте
        try:
            hostname = socket.gethostname()
            self.es_additional_fields.setdefault('host', hostname)
            self.es_additional_fields.setdefault('host_ip', socket.gethostbyname(hostname))
        except Exception:
            self.es_additional_fields.setdefault('host', 'unknown')
            self.es_additional_fields.setdefault('host_ip', '127.0.0.1')
        
        self.es_client = None
        self._connect()
        
        # Настраиваем шаблон индекса
        self._setup_index_template()

    def _connect(self) -> None:
        """Создание подключения к Elasticsearch."""
        try:
            # Настройки аутентификации
            auth_params = {}
            if self.auth_details:
                auth_params = {'http_auth': (self.auth_details.get('username'), 
                                           self.auth_details.get('password'))}
            
            # Проверяем и форматируем URL
            es_host = self.es_host
            if not es_host.startswith(('http://', 'https://')):
                es_host = f"http://{es_host}"
            
            # Параметры соединения с таймаутами
            connection_params = {
                'timeout': 10,
                'retry_on_timeout': True,
                'max_retries': 3
            }
            connection_params.update(auth_params)
            
            # Создаем клиент Elasticsearch
            print(f"Подключаемся к Elasticsearch: {es_host}")
            self.es_client = Elasticsearch([es_host], **connection_params)
            
            # Проверяем соединение
            if not self.es_client.ping():
                print(f"Не удалось подключиться к Elasticsearch по адресу {es_host}")
                self.es_client = None
            else:
                print(f"Успешно подключились к Elasticsearch: {es_host}")
        except Exception as e:
            print(f"Ошибка при подключении к Elasticsearch: {e}")
            self.es_client = None
    
    def _setup_index_template(self) -> None:
        """Настройка шаблона индекса при инициализации."""
        if self.es_client:
            setup_elasticsearch_index_template(
                es_host=self.es_host,
                template_name='exchange-logs-template',
                index_pattern='exchange_logs-*'
            )

    def _get_daily_index_name(self) -> str:
        """
        Формирование имени индекса с датой.
        Пример: logs-exchange-2023.01.01
        """
        now = datetime.datetime.utcnow()
        date_suffix = now.strftime('%Y.%m.%d')
        return f"{self.es_index_name}-{date_suffix}"

    def emit(self, record: logging.LogRecord) -> None:
        """
        Отправка записи лога в Elasticsearch.
        """
        # Пытаемся создать соединение, если оно не существует
        if not self.es_client:
            self._connect()
            if not self.es_client:
                # Если соединение не удалось создать, делаем запись только в локальный лог
                self.handleError(record)
                return

        try:
            log_entry = self._format_log_record(record)
            # Пытаемся отправить запись в Elasticsearch
            self.es_client.index(
                index=self._get_daily_index_name(),
                body=log_entry
            )
        except Exception as e:
            # Если не удалось отправить, пытаемся переподключиться один раз
            try:
                # Пробуем переподключиться
                self._connect()
                if self.es_client:
                    # Если удалось переподключиться, пробуем отправить снова
                    log_entry = self._format_log_record(record)
                    self.es_client.index(
                        index=self._get_daily_index_name(),
                        body=log_entry
                    )
            except Exception:
                # Если обе попытки не удались, обрабатываем ошибку
                # Но не блокируем приложение из-за ошибки логирования
                self.handleError(record)

    def _format_log_record(self, record: logging.LogRecord) -> Dict[str, Any]:
        """
        Форматирование записи лога для отправки в Elasticsearch.
        """
        # Базовые поля лога
        log_record = {
            'timestamp': datetime.datetime.utcnow().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'module': record.module,
            'funcName': record.funcName,
            'lineNo': record.lineno,
            'message': self.format(record) if self.formatter else record.getMessage(),
        }

        # Если есть исключение, добавляем его информацию
        if record.exc_info:
            log_record['exception'] = {
                'type': record.exc_info[0].__name__,
                'message': str(record.exc_info[1]),
                'traceback': traceback.format_exception(*record.exc_info)
            }

        # Добавляем все дополнительные поля
        log_record.update(self.es_additional_fields)

        # Добавляем все пользовательские атрибуты
        for key, value in record.__dict__.items():
            if key not in ('args', 'asctime', 'created', 'exc_info', 'exc_text', 'filename',
                           'funcName', 'id', 'levelname', 'levelno', 'lineno', 'module',
                           'msecs', 'message', 'msg', 'name', 'pathname', 'process',
                           'processName', 'relativeCreated', 'stack_info', 'thread', 'threadName'):
                log_record[key] = value

        return log_record

    def close(self) -> None:
        """
        Закрытие соединения с Elasticsearch при завершении работы.
        """
        if self.es_client:
            self.es_client.close()
        super().close() 