import logging
import json
import datetime
import socket
from urllib.parse import urljoin
import requests


class ElasticsearchLogHandler(logging.Handler):
    """
    Обработчик логов, отправляющий записи в Elasticsearch
    """
    
    def __init__(self, host, index_prefix='python-logs-', level=logging.INFO):
        """
        Инициализация обработчика для Elasticsearch
        
        :param host: URL Elasticsearch сервера (например, http://elasticsearch:9200)
        :param index_prefix: Префикс для индекса Elasticsearch (будет добавлена дата)
        :param level: Уровень логирования
        """
        super().__init__(level)
        self.host = host
        self.index_prefix = index_prefix
        self.hostname = socket.gethostname()
    
    def _get_index_name(self):
        """Формирование имени индекса с добавлением текущей даты"""
        now = datetime.datetime.now()
        index_name = f"{self.index_prefix}{now.strftime('%Y.%m.%d')}"
        return index_name
    
    def emit(self, record):
        """
        Отправка записи лога в Elasticsearch
        
        :param record: Запись лога для отправки
        """
        try:
            # Форматируем запись лога
            msg = self.format(record)
            
            # Создаем документ для Elasticsearch
            document = {
                'timestamp': datetime.datetime.now().isoformat(),
                'level': record.levelname,
                'message': msg,
                'logger': record.name,
                'path': record.pathname,
                'line_number': record.lineno,
                'function': record.funcName,
                'process': record.process,
                'thread': record.thread,
                'hostname': self.hostname
            }
            
            # Добавляем ключевую информацию из exc_info если есть
            if record.exc_info:
                document['exception'] = {
                    'type': str(record.exc_info[0].__name__),
                    'message': str(record.exc_info[1]),
                }
            
            # Формируем URL для отправки данных в Elasticsearch
            index_name = self._get_index_name()
            url = urljoin(self.host, f"{index_name}/_doc")
            
            # Отправляем данные в Elasticsearch
            response = requests.post(
                url, 
                data=json.dumps(document),
                headers={"Content-Type": "application/json"}
            )
            
            # Проверяем статус ответа
            if response.status_code >= 400:
                print(f"Ошибка при отправке лога в Elasticsearch: {response.text}")
                
        except Exception as e:
            # Если произошла ошибка при отправке, печатаем сообщение об ошибке
            print(f"Ошибка при попытке отправить лог в Elasticsearch: {str(e)}")


def setup_elasticsearch_index_template(es_host, template_name='python-logs-template', index_pattern='python-app-logs-*'):
    """
    Создает шаблон индекса в Elasticsearch
    
    :param es_host: URL Elasticsearch сервера
    :param template_name: Имя шаблона
    :param index_pattern: Шаблон имени индекса
    :return: True если успешно, False в противном случае
    """
    try:
        template_url = urljoin(es_host, f"_index_template/{template_name}")
        
        # Определяем шаблон индекса
        template = {
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
                        "message": {"type": "text"},
                        "logger": {"type": "keyword"},
                        "path": {"type": "keyword"},
                        "line_number": {"type": "integer"},
                        "function": {"type": "keyword"},
                        "process": {"type": "integer"},
                        "thread": {"type": "integer"},
                        "hostname": {"type": "keyword"},
                        "exception": {
                            "properties": {
                                "type": {"type": "keyword"},
                                "message": {"type": "text"}
                            }
                        }
                    }
                }
            }
        }
        
        # Отправляем запрос на создание шаблона
        response = requests.put(
            template_url,
            data=json.dumps(template),
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code >= 400:
            print(f"Ошибка при создании шаблона индекса в Elasticsearch: {response.text}")
            return False
        
        print(f"Шаблон индекса {template_name} успешно создан в Elasticsearch")
        return True
        
    except Exception as e:
        print(f"Ошибка при попытке создать шаблон индекса в Elasticsearch: {str(e)}")
        return False


# Конфигурация для Elasticsearch Handler
def get_elasticsearch_config(es_host='http://elasticsearch:9200'):
    """
    Получить конфигурацию логирования для Elasticsearch
    
    :param es_host: URL Elasticsearch сервера
    :return: Словарь с конфигурацией
    """
    
    elasticsearch_config = {
        'formatters': {
            'elasticsearch_formatter': {
                'format': '%(asctime)s [%(process)d] [%(levelname)s] %(message)s',
                'datefmt': '[%Y-%m-%d %H:%M:%S %z]',
                'class': 'logging.Formatter',
            },
        },
        'handlers': {
            'elasticsearch_handler': {
                'class': 'app.core.logs.elasticsearch_logger.ElasticsearchLogHandler',
                'formatter': 'elasticsearch_formatter',
                'level': 'INFO',
                'host': es_host,
                'index_prefix': 'python-app-logs-',
            },
        },
        'loggers': {}
    }
    
    return elasticsearch_config 