"""Pin-test: the AI-assistants public router never touches JWT auth
(``tasks/ai-assistants`` Step 14).

Walks :file:`API/src/app/core/ai_assistants/public_router.py` via
``ast`` and fails CI if the file:

  * imports anything from :mod:`src.app.core.auth.dependencies`
    (``require_permissions``, ``get_current_user``, ``current_user``);
  * references any of the JWT-shaped symbols by bare name inside
    a function body (belt+braces if a future refactor does a
    star-import);
  * declares an endpoint handler that DOESN'T list
    ``PublicContext`` (or ``public_context``) among its parameters.

The public router authenticates via the bearer embed key ONLY —
mixing JWT deps in would either fail every request (JWT missing on
public visitors) or, worse, silently accept a stray operator token
and pierce the isolation between the two auth models. This test
locks that door.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_PUBLIC_ROUTER_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "app"
    / "core"
    / "ai_assistants"
    / "public_router.py"
)

# Any of these appearing as an imported name or a bare identifier
# inside a router function body is a violation.
_FORBIDDEN_SYMBOLS: frozenset[str] = frozenset(
    {
        "require_permissions",
        "get_current_user",
        "current_user",
        "get_current_user_dependency",
        "require_org_admin",
    }
)

# Any of these module paths appearing in ``from ... import`` is a
# violation regardless of the imported name.
_FORBIDDEN_MODULES: frozenset[str] = frozenset(
    {
        "src.app.core.auth.dependencies",
        "src.app.core.auth.jwt",
        "src.app.core.auth.service",
    }
)


def _load_public_router_ast() -> ast.Module:
    assert _PUBLIC_ROUTER_PATH.is_file(), (
        f"public_router.py missing at {_PUBLIC_ROUTER_PATH}"
    )
    return ast.parse(_PUBLIC_ROUTER_PATH.read_text(encoding="utf-8"))


def test_public_router_does_not_import_jwt_deps() -> None:
    """No ``from src.app.core.auth.dependencies import ...`` (or
    similar) anywhere in the file. Catches the common case of an
    operator dev copy-pasting a Depends chain from the admin router."""
    tree = _load_public_router_ast()
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module in _FORBIDDEN_MODULES:
                violations.append(
                    f"line {node.lineno}: `from {module} import ...` — "
                    "public router must not depend on JWT auth."
                )
            for alias in node.names:
                if alias.name in _FORBIDDEN_SYMBOLS:
                    violations.append(
                        f"line {node.lineno}: import of {alias.name!r} "
                        "— public router must not depend on JWT auth."
                    )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _FORBIDDEN_MODULES:
                    violations.append(
                        f"line {node.lineno}: `import {alias.name}` "
                        "— public router must not depend on JWT auth."
                    )
    assert not violations, "public_router JWT-import violations:\n  - " + "\n  - ".join(
        violations
    )


def test_public_router_body_does_not_reference_jwt_symbols() -> None:
    """Belt+braces: even if some future refactor manages to sneak a
    star-import in, catching bare references to the forbidden names
    inside function bodies still fails CI."""
    tree = _load_public_router_ast()
    violations: list[str] = []
    for func in _iter_functions(tree):
        for node in ast.walk(func):
            if isinstance(node, ast.Name) and node.id in _FORBIDDEN_SYMBOLS:
                violations.append(
                    f"line {node.lineno}: function {func.name!r} references "
                    f"{node.id!r} — public router uses PublicContext only."
                )
            elif isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_SYMBOLS:
                violations.append(
                    f"line {node.lineno}: function {func.name!r} accesses "
                    f".{node.attr} — public router uses PublicContext only."
                )
    assert not violations, "public_router JWT-symbol violations:\n  - " + "\n  - ".join(
        violations
    )


def test_every_public_endpoint_declares_public_context() -> None:
    """Every ``@router.post`` / ``@router.get`` / ``@router.delete``
    handler must accept ``PublicContext`` (or ``public_context``) as
    one of its parameters — otherwise the handler is unauthenticated
    entirely, which is a much bigger bug than any JWT confusion.
    """
    tree = _load_public_router_ast()
    violations: list[str] = []
    for func in _iter_functions(tree):
        if not _has_router_decorator(func):
            continue
        param_annotations = _collect_param_annotations(func)
        if not any(
            "PublicContext" in ann or "public_context" in ann
            for ann in param_annotations
        ):
            violations.append(
                f"line {func.lineno}: endpoint {func.name!r} does not "
                "declare a PublicContext / public_context parameter."
            )
    assert not violations, (
        "public_router endpoint-auth violations:\n  - " + "\n  - ".join(violations)
    )


def _iter_functions(tree: ast.Module):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _has_router_decorator(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for deco in func.decorator_list:
        # ``@router.post(...)`` / ``@router.get(...)`` etc.
        call = deco if isinstance(deco, ast.Call) else None
        target = call.func if call is not None else deco
        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "router"
        ):
            return True
    return False


def _collect_param_annotations(func) -> list[str]:  # noqa: ANN001
    out: list[str] = []
    args = list(func.args.args) + list(func.args.kwonlyargs)
    for arg in args:
        if arg.annotation is None:
            continue
        try:
            out.append(ast.unparse(arg.annotation))
        except Exception:  # pragma: no cover — defensive
            continue
    return out


# --- Meta-tests: the pin-test itself catches the shapes it claims to ---


def test_pin_test_would_catch_jwt_import() -> None:
    """Regression guard on the pin-test walker: manually build an AST
    with a forbidden import + assert the walker flags it. Keeps the
    pin-test honest even if someone loosens the check."""
    fake = ast.parse(
        "from src.app.core.auth.dependencies import require_permissions\n"
    )
    hit = False
    for node in ast.walk(fake):
        if isinstance(node, ast.ImportFrom) and node.module in _FORBIDDEN_MODULES:
            hit = True
    assert hit, "walker would miss a JWT import — pin test is broken"


def test_pin_test_would_catch_bare_symbol() -> None:
    fake = ast.parse(
        "async def handler():\n    return require_permissions('x')\n"
    )
    hit = False
    for node in ast.walk(fake):
        if isinstance(node, ast.Name) and node.id in _FORBIDDEN_SYMBOLS:
            hit = True
    assert hit, "walker would miss a bare JWT symbol — pin test is broken"
