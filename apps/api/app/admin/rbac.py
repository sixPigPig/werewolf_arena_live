from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping


class AdminRole(StrEnum):
    VIEWER = "viewer"
    CONTENT_EDITOR = "content_editor"
    OPERATOR = "operator"
    SUPER_ADMIN = "super_admin"


class AdminPermission(StrEnum):
    OVERVIEW_READ = "overview.read"
    RUNS_READ = "runs.read"
    RUNS_DEBUG_READ = "runs.debug.read"
    RUNS_CONTROL = "runs.control"
    GAMES_READ = "games.read"
    GAMES_DEBUG_READ = "games.debug.read"
    PLAYERS_READ = "players.read"
    PLAYERS_WRITE = "players.write"
    PLAYERS_PUBLISH = "players.publish"
    PLAYERS_ARCHIVE = "players.archive"
    PLAYERS_AI_GENERATE = "players.ai_generate"
    VOICE_READ = "voice.read"
    VOICE_GENERATE_MISSING = "voice.generate_missing"
    VOICE_REGENERATE_ALL = "voice.regenerate_all"
    USERS_MANAGE = "users.manage"
    ROLES_MANAGE = "roles.manage"
    AUDIT_READ = "audit.read"
    SETTINGS_READ = "settings.read"
    SETTINGS_MANAGE = "settings.manage"


_VIEWER_PERMISSIONS = frozenset(
    {
        AdminPermission.OVERVIEW_READ,
        AdminPermission.RUNS_READ,
        AdminPermission.GAMES_READ,
        AdminPermission.PLAYERS_READ,
        AdminPermission.VOICE_READ,
        AdminPermission.SETTINGS_READ,
    }
)

ROLE_PERMISSIONS: Final[Mapping[AdminRole, frozenset[AdminPermission]]] = MappingProxyType(
    {
        AdminRole.VIEWER: _VIEWER_PERMISSIONS,
        AdminRole.CONTENT_EDITOR: _VIEWER_PERMISSIONS
        | {
            AdminPermission.PLAYERS_WRITE,
            AdminPermission.PLAYERS_PUBLISH,
            AdminPermission.PLAYERS_ARCHIVE,
            AdminPermission.PLAYERS_AI_GENERATE,
            AdminPermission.VOICE_GENERATE_MISSING,
        },
        AdminRole.OPERATOR: _VIEWER_PERMISSIONS
        | {
            AdminPermission.RUNS_CONTROL,
            AdminPermission.RUNS_DEBUG_READ,
            AdminPermission.GAMES_DEBUG_READ,
        },
        AdminRole.SUPER_ADMIN: frozenset(AdminPermission),
    }
)


def permissions_for_role(role: str | AdminRole | None) -> frozenset[AdminPermission]:
    if role is None:
        return frozenset()
    try:
        normalized_role = AdminRole(role)
    except ValueError:
        return frozenset()
    return ROLE_PERMISSIONS[normalized_role]
