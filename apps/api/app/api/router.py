from fastapi import APIRouter

from app.api.routes.games import router as games_router
from app.api.routes.health import router as health_router


api_router = APIRouter()
api_router.include_router(games_router, prefix="/games", tags=["games"])
api_router.include_router(health_router, prefix="/health", tags=["health"])
