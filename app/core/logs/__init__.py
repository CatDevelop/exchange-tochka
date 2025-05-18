import os
from app.core.logs.logs import debug_logger, info_logger, error_logger
from app.core.logs.elasticsearch_logger import setup_elasticsearch_index_template


# Получение URL Elasticsearch из переменной окружения или использование значения по умолчанию
ELASTICSEARCH_HOST = os.environ.get('ELASTICSEARCH_HOST', 'http://elasticsearch:9200')

# Настройка шаблона индекса при импорте модуля
try:
    setup_elasticsearch_index_template(
        es_host=ELASTICSEARCH_HOST,
        template_name='python-logs-template',
        index_pattern='python-app-logs-*'
    )
except Exception as e:
    print(f"Невозможно настроить шаблон индекса Elasticsearch: {e}")
