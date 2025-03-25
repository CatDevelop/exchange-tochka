from app.core.config import settings

workers = settings.app.workers
worker_class = 'uvicorn.workers.UvicornWorker'
bind = '0.0.0.0:8000'
timeout = 300
keepalive = 5
