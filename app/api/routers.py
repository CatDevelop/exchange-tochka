from fastapi import APIRouter

from app.api.endpoints import health_router, instrument_router, user_router

main_router = APIRouter()

main_router.include_router(health_router)
main_router.include_router(user_router)
main_router.include_router(instrument_router)
