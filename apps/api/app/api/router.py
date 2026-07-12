from fastapi import APIRouter

from app.api.routes.admin_auth import router as admin_auth_router
from app.api.routes.admin_dashboard import router as admin_dashboard_router
from app.api.routes.admin_games import router as admin_games_router
from app.api.routes.admin_live_runs import router as admin_live_runs_router
from app.api.routes.admin_player_profiles import router as admin_player_profiles_router
from app.api.routes.admin_rule_sets import router as admin_rule_sets_router
from app.api.routes.admin_system import router as admin_system_router
from app.api.routes.admin_voice_assets import router as admin_voice_assets_router
from app.api.routes.games import router as games_router
from app.api.routes.health import router as health_router
from app.api.routes.judge_voice_assets import router as judge_voice_assets_router
from app.api.routes.metrics import router as metrics_router
from app.api.routes.player_profiles import router as player_profiles_router
from app.api.routes.public_player_profiles import router as public_player_profiles_router
from app.api.routes.public_session import router as public_session_router


api_router = APIRouter()
api_router.include_router(admin_auth_router, prefix="/admin", tags=["admin-auth"])
api_router.include_router(admin_dashboard_router, prefix="/admin", tags=["admin-dashboard"])
api_router.include_router(admin_games_router, prefix="/admin", tags=["admin-games"])
api_router.include_router(admin_live_runs_router, prefix="/admin", tags=["admin-live-runs"])
api_router.include_router(admin_rule_sets_router, prefix="/admin", tags=["admin-rule-sets"])
api_router.include_router(admin_system_router, prefix="/admin", tags=["admin-system"])
api_router.include_router(
    admin_voice_assets_router,
    prefix="/admin",
    tags=["admin-voice-assets"],
)
api_router.include_router(
    admin_player_profiles_router,
    prefix="/admin",
    tags=["admin-player-profiles"],
)
api_router.include_router(games_router, prefix="/games", tags=["games"])
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(metrics_router, prefix="/metrics", tags=["metrics"])
api_router.include_router(
    judge_voice_assets_router,
    prefix="/judge-voice-lines",
    tags=["judge-voice-lines"],
)
api_router.include_router(
    player_profiles_router, prefix="/player-profiles", tags=["player-profiles"]
)
api_router.include_router(
    public_player_profiles_router,
    prefix="/public/player-profiles",
    tags=["public-player-profiles"],
)
api_router.include_router(
    public_session_router,
    prefix="/public",
    tags=["public-session"],
)
