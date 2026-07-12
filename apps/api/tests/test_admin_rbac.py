from app.admin.rbac import AdminPermission, AdminRole, ROLE_PERMISSIONS, permissions_for_role


def test_fixed_roles_have_expected_permission_boundaries() -> None:
    viewer = ROLE_PERMISSIONS[AdminRole.VIEWER]
    content_editor = ROLE_PERMISSIONS[AdminRole.CONTENT_EDITOR]
    operator = ROLE_PERMISSIONS[AdminRole.OPERATOR]
    super_admin = ROLE_PERMISSIONS[AdminRole.SUPER_ADMIN]

    assert viewer == {
        AdminPermission.OVERVIEW_READ,
        AdminPermission.RUNS_READ,
        AdminPermission.GAMES_READ,
        AdminPermission.PLAYERS_READ,
        AdminPermission.RULES_READ,
        AdminPermission.VOICE_READ,
        AdminPermission.SETTINGS_READ,
    }
    assert viewer < content_editor
    assert viewer < operator
    assert AdminPermission.PLAYERS_WRITE in content_editor
    assert AdminPermission.RULES_WRITE in content_editor
    assert AdminPermission.RULES_PUBLISH not in content_editor
    assert AdminPermission.RULES_ARCHIVE not in content_editor
    assert AdminPermission.RULES_SET_DEFAULT not in content_editor
    assert AdminPermission.RUNS_CONTROL not in content_editor
    assert AdminPermission.RUNS_CONTROL in operator
    assert AdminPermission.RUNS_DEBUG_READ in operator
    assert AdminPermission.RUNS_DEBUG_READ not in viewer
    assert AdminPermission.PLAYERS_WRITE not in operator
    assert AdminPermission.RULES_READ in operator
    assert AdminPermission.RULES_WRITE not in operator
    assert super_admin == frozenset(AdminPermission)


def test_unknown_or_missing_role_has_no_permissions() -> None:
    assert permissions_for_role(None) == frozenset()
    assert permissions_for_role("unknown") == frozenset()
