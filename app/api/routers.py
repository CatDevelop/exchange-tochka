from fastapi import APIRouter

from app.api.endpoints import balance_router, health_router, user_router

main_router = APIRouter()

main_router.include_router(health_router)
main_router.include_router(user_router)
main_router.include_router(balance_router)
