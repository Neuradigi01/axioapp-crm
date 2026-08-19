"""RBAC + router-registration sanity for AI Assistants.

Verifies:
  * Router endpoint list matches the step spec (6 endpoints, right
    HTTP verbs).
  * Each endpoint declares the correct permission dependency
    (``ai_assistants.view`` on GETs, ``ai_assistants.manage`` on
    mutations).
  * ``require_permissions`` is imported + wired at every gate.

The full "user with only .view calling POST → 403" flow is a
FastAPI TestClient assertion — deferred to a future integration
sweep (this repo doesn't have a canonical test-client fixture that
provides a JWT + permission bag; the individual permission-check
tests in ``core/permissions/`` already cover the dependency's own
semantics). What we CAN pin at unit level: every endpoint declares
the right dependency, so a code change that swaps ``.manage`` for
``.view`` (or drops the guard entirely) fails this test.
"""

from __future__ import annotations

import inspect

import src.app.core.ai_assistants.models  # noqa: F401,E402 — metadata registration


def test_router_has_seven_endpoints() -> None:
    from src.app.core.ai_assistants.router import router

    endpoints = {(tuple(sorted(r.methods)), r.path) for r in router.routes if hasattr(r, "methods")}
    expected = {
        (("GET",), "/ai-assistants"),
        (("GET",), "/ai-assistants/{assistant_id}"),
        (("POST",), "/ai-assistants"),
        (("PATCH",), "/ai-assistants/{assistant_id}"),
        (("POST",), "/ai-assistants/{assistant_id}/archive"),
        (("DELETE",), "/ai-assistants/{assistant_id}"),
        # tasks/ai-assistants Step 9 — operator preview SSE.
        (("POST",), "/ai-assistants/{assistant_id}/preview"),
    }
    assert endpoints == expected, f"router shape drift: {endpoints ^ expected}"


def _dependency_permission_keys(route) -> set[str]:  # noqa: ANN001
    """Walk a route's dependencies and return the permission keys
    the ``require_permissions(...)`` factory closed over. Peeks at
    the closure of the ``_check`` inner function each factory returns."""
    keys: set[str] = set()
    for dep in route.dependant.dependencies:
        call = dep.call
        if call is None:
            continue
        # require_permissions() returns an inner `_check` async fn
        # whose closure carries the `required` tuple.
        if inspect.iscoroutinefunction(call) and getattr(call, "__name__", "") == "_check":
            cells = call.__closure__ or ()
            for cell in cells:
                try:
                    value = cell.cell_contents
                except ValueError:
                    continue
                if isinstance(value, tuple) and all(isinstance(v, str) for v in value):
                    keys.update(value)
        # Recurse — some routes wrap deps in more deps.
        keys.update(_dependency_permission_keys_from_subdeps(dep))
    return keys


def _dependency_permission_keys_from_subdeps(dep) -> set[str]:  # noqa: ANN001
    keys: set[str] = set()
    for sub in dep.dependencies:
        call = sub.call
        if call is None:
            continue
        if inspect.iscoroutinefunction(call) and getattr(call, "__name__", "") == "_check":
            cells = call.__closure__ or ()
            for cell in cells:
                try:
                    value = cell.cell_contents
                except ValueError:
                    continue
                if isinstance(value, tuple) and all(isinstance(v, str) for v in value):
                    keys.update(value)
        keys.update(_dependency_permission_keys_from_subdeps(sub))
    return keys


def test_gets_require_view_permission() -> None:
    from src.app.core.ai_assistants.router import router

    for route in router.routes:
        if not hasattr(route, "methods") or "GET" not in route.methods:
            continue
        keys = _dependency_permission_keys(route)
        assert "ai_assistants.view" in keys, (
            f"GET {route.path} missing ai_assistants.view permission gate; keys={keys}"
        )


def test_mutations_require_manage_permission() -> None:
    """Every state-mutating endpoint (create / update / archive /
    delete) requires ``ai_assistants.manage``. The POST ``/preview``
    endpoint is a read-only interactive tool (streams a reply without
    persisting operator intent) and gates on ``.view`` instead —
    kept out of the mutation set explicitly."""
    from src.app.core.ai_assistants.router import router

    mutation_verbs = {"POST", "PATCH", "DELETE"}
    # The preview endpoint POSTs to trigger a one-shot chat turn but
    # doesn't mutate assistant state; view is the correct gate.
    _READ_ONLY_POSTS = {"/ai-assistants/{assistant_id}/preview"}
    for route in router.routes:
        if not hasattr(route, "methods"):
            continue
        if not (route.methods & mutation_verbs):
            continue
        if route.path in _READ_ONLY_POSTS:
            continue
        keys = _dependency_permission_keys(route)
        assert "ai_assistants.manage" in keys, (
            f"{route.methods} {route.path} missing ai_assistants.manage; keys={keys}"
        )


def test_no_endpoint_is_unauthenticated() -> None:
    """Sanity: every endpoint declares at least one permission gate.
    Catches an accidental drop of ``Depends(require_permissions(...))``
    which would fall through to unauthenticated public access."""
    from src.app.core.ai_assistants.router import router

    for route in router.routes:
        if not hasattr(route, "methods"):
            continue
        keys = _dependency_permission_keys(route)
        assert keys, f"{route.methods} {route.path} has no permission gate"
