from fastapi import APIRouter

from app.core.logs.logs import no_log
from app.core.logs.logs import debug_logger, info_logger, error_logger

router = APIRouter(prefix='', tags=['health'])


@router.get('/health')
@no_log()
async def health() -> bool:
    return True


@router.get("/test-logs")
async def test_logs() -> dict:
    debug_logger.debug("Тестовый DEBUG лог")
    info_logger.info("Тестовый INFO лог")
    error_logger.error("Тестовый ERROR лог")
    
    return {
        "status": "Logs sent",
        "message": "Проверьте логи в Elasticsearch/Kibana"
    }