"""Router + module-registry registration smoke tests — no live DB or
HTTP.

Full auth-required behavioural tests (403 on missing permission,
404 cross-org, 409 stale version, etc) live in
``test_router_endpoints.py`` and need the async client + auth
fixture — deferred to the batch pytest run per memory
``feedback_pause_before_pytest.md``.
"""

from __future__ import annotations


def test_module_descriptor_registered_with_correct_fields() -> None:
    from src.app.core.chatbots.module import MODULE

    assert MODULE.id == "chatbots"
    assert MODULE.name == "Chat Bots"
    assert MODULE.icon == "bot"
    assert MODULE.layer == "core"
    assert MODULE.route == "/api/v1/chatbots"
    assert MODULE.frontend_route == "/user/chatbots"
    assert MODULE.section == "Automation"
    assert MODULE.menu_position == 720
    assert set(MODULE.permissions) == {
        "chatbots.view",
        "chatbots.edit",
        "chatbots.publish",
        "chatbots.delete",
    }


def test_permission_key_constants_match_module_declaration() -> None:
    from src.app.core.chatbots import permissions as perms
    from src.app.core.chatbots.module import MODULE

    assert set(MODULE.permissions) == set(perms.ALL_KEYS)


def test_owner_and_admin_hold_every_key() -> None:
    from src.app.core.chatbots import permissions as perms

    assert set(perms.OWNER_KEYS) == set(perms.ALL_KEYS)
    assert set(perms.ADMIN_KEYS) == set(perms.ALL_KEYS)


def test_employee_holds_view_only() -> None:
    from src.app.core.chatbots import permissions as perms

    assert set(perms.EMPLOYEE_KEYS) == {perms.PERM_VIEW}


def test_router_declares_expected_endpoints() -> None:
    """Guardrail — every endpoint from the Step-3 spec must appear
    exactly once. Prevents accidental deletion + accidental duplicate
    path registration."""
    from src.app.core.chatbots.router import router

    paths_by_method: dict[tuple[str, str], int] = {}
    for route in router.routes:
        if not hasattr(route, "methods") or not hasattr(route, "path"):
            continue
        for method in route.methods:
            if method == "HEAD":
                continue
            key = (method, route.path)
            paths_by_method[key] = paths_by_method.get(key, 0) + 1

    expected = {
        ("GET", "/chatbots/save-targets"),
        ("GET", "/chatbots"),
        ("POST", "/chatbots"),
        ("GET", "/chatbots/{chatbot_id}"),
        ("PATCH", "/chatbots/{chatbot_id}"),
        ("POST", "/chatbots/{chatbot_id}/publish"),
        ("POST", "/chatbots/{chatbot_id}/pause"),
        ("DELETE", "/chatbots/{chatbot_id}"),
        ("GET", "/chatbots/{chatbot_id}/versions"),
        ("POST", "/chatbots/{chatbot_id}/versions/{version_id}/rollback"),
    }
    missing = expected - set(paths_by_method)
    duplicated = {k for k, v in paths_by_method.items() if v > 1}
    assert not missing, f"missing router endpoints: {missing}"
    assert not duplicated, f"duplicated router endpoints: {duplicated}"


def test_role_templates_include_chatbot_keys() -> None:
    """Admin + Owner grants include all 4 keys; Employee gets view."""
    from src.app.core.permissions import role_templates as rt

    admin_keys = set(rt._CORE_ADMIN_KEYS)
    employee_keys = set(rt._CORE_EMPLOYEE_KEYS)

    assert {"chatbots.view", "chatbots.edit", "chatbots.publish", "chatbots.delete"}.issubset(
        admin_keys
    )
    assert "chatbots.view" in employee_keys
    assert "chatbots.edit" not in employee_keys
    assert "chatbots.publish" not in employee_keys
    assert "chatbots.delete" not in employee_keys
