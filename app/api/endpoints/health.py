from fastapi import APIRouter

from app.core.logs.logs import no_log

router = APIRouter(prefix='', tags=['health'])


@router.get('/health')
@no_log()
async def health() -> bool:
    return True
