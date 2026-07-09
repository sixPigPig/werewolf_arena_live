from fastapi import APIRouter

from app.api.routes.games import router as games_router
from app.api.routes.health import router as health_router
from app.api.routes.judge_voice_assets import router as judge_voice_assets_router
from app.api.routes.player_profiles import router as player_profiles_router


api_router = APIRouter()
api_router.include_router(games_router, prefix="/games", tags=["games"])
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(
    judge_voice_assets_router,
    prefix="/judge-voice-lines",
    tags=["judge-voice-lines"],
)
api_router.include_router(player_profiles_router, prefix="/player-profiles", tags=["player-profiles"])
