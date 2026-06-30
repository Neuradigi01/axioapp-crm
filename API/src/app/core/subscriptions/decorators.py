"""Route-level entitlement gates.

Two decorators let a FastAPI route declaratively require either a plan
feature or available capacity for a resource. Both rely on the
per-request ``Entitlements`` bundle injected by ``get_entitlements``;
multiple gates on the same route share that bundle (FastAPI dedupes
the dependency call), so stacking ``@requires_feature`` and
``@enforces_cap`` costs at most one extra DB read per request.

Usage
-----

::

    from src.app.core.subscriptions.decorators import (
        requires_feature, enforces_cap,
    )
    from src.app.core.subscriptions.feature_keys import (
        FEATURE_AUTOMATION_WORKFLOWS,
    )

    @router.post("/automation/workflows")             # FastAPI decorator OUTERMOST
    @requires_feature(FEATURE_AUTOMATION_WORKFLOWS)
    async def create_workflow(...):
        ...

    @router.post("/contacts")
    @enforces_cap("contacts", current_provider=count_org_contacts)
    async def create_contact(...):
        ...

Decorator order matters: the FastAPI route decorator (``@router.post``)
must sit OUTSIDE the entitlement decorators so it sees the augmented
signature (with the injected ``Entitlements`` dependency) and registers
the route correctly.

Scope (per spec)
----------------

- These gates check ``feature_locked`` and ``cap_reached`` only.
- They do NOT short-circuit on ``is_read_only`` — that is Step 10's
  middleware, which sits earlier in the request lifecycle. A read-only
  org is already blocked by then, so by the time these decorators run
  the subscription is writeable.
- On failure they raise ``EntitlementError`` (HTTP 402). The legacy
  ``http_exception_handler`` in ``main.py`` passes the structured
  ``detail`` dict through verbatim.
"""

from __future__ import annotations

import functools
import inspect
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Depends

from src.app.core.subscriptions.dependencies import get_entitlements
from src.app.core.subscriptions.entitlements import (
    Entitlements,
    _lowest_plan_granting_feature,
    _lowest_plan_with_higher_cap,
)
from src.app.core.subscriptions.exceptions import EntitlementError

# Callable signature for ``enforces_cap``'s count source. The provider
# receives the caller's ``org_id`` and returns either an ``int`` or an
# awaitable that resolves to one. Sync providers are accepted so tests
# (and trivial constant providers) can stay terse; production usage in
# Step 5 will hand in an awaitable backed by the ``usage_counters``
# denormalised counter.
CapCountProvider = Callable[[uuid.UUID], int | Awaitable[int]]


# Unique sentinel kwarg names. Picked so they cannot collide with any
# parameter a handler would legitimately declare; stacking the two
# decorators picks two distinct names so each wrapper extracts its own
# bundle without stepping on the other's kwargs.
_FEATURE_KW = "__entitlements_feature_gate__"
_CAP_KW = "__entitlements_cap_gate__"


def requires_feature(key: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Block the route unless the caller's plan grants ``key``.

    Resolves the caller's :class:`Entitlements` via FastAPI dependency
    injection, then checks :meth:`Entitlements.has_feature`. If the plan
    does not grant the feature, raises
    ``EntitlementError(reason='feature_locked', required_plan=<cheapest tier>)``
    so the frontend can render the right upgrade prompt.

    Unknown feature keys (typos) resolve to False on the
    ``Entitlements`` side and would always 402 — use the constants in
    :mod:`feature_keys` to prevent that drift.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if not inspect.iscoroutinefunction(func):
            raise TypeError(
                f"requires_feature can only wrap async def handlers; {func.__qualname__} is sync."
            )

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            entitlements: Entitlements = kwargs.pop(_FEATURE_KW)
            if not entitlements.has_feature(key):
                required = _lowest_plan_granting_feature(key)
                message = (
                    f"This feature requires the {required.title()} plan or higher."
                    if required
                    else "This feature is not available on any plan."
                )
                raise EntitlementError(
                    "feature_locked",
                    required_plan=required,
                    message=message,
                )
            return await func(*args, **kwargs)

        wrapper.__signature__ = _inject_entitlements_param(func, _FEATURE_KW)  # type: ignore[attr-defined]
        return wrapper

    return decorator


def enforces_cap(
    resource: str, *, current_provider: CapCountProvider
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Block the write if it would push the org over the plan's cap.

    The decorator runs AFTER FastAPI's dependency resolution (so the
    request is already authenticated and the org is known) and BEFORE
    the handler body. It calls ``current_provider(org_id)`` to obtain
    the current count for ``resource``, then asks
    :meth:`Entitlements.is_within_cap` whether adding one more would fit.

    On failure, raises ``EntitlementError(reason='cap_reached',
    resource=..., cap=..., required_plan=<next tier with headroom>)``.

    ``current_provider`` may be sync or async; both are awaited safely.
    Unlimited caps (``-1``) always pass without invoking the provider's
    expensive count, but the provider IS still called when the cap is
    finite — guard the provider against frequent calls if it touches
    the DB. Step 5's ``usage_counters`` table is the production-grade
    counter for hot paths.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if not inspect.iscoroutinefunction(func):
            raise TypeError(
                f"enforces_cap can only wrap async def handlers; {func.__qualname__} is sync."
            )

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            entitlements: Entitlements = kwargs.pop(_CAP_KW)
            cap = entitlements.cap_for(resource)

            # Unlimited short-circuits without counting — counts can be
            # expensive on busy orgs, and the answer is fixed at True.
            if cap != -1:
                current = await _resolve_count(current_provider, entitlements.org_id)
                if not entitlements.is_within_cap(resource, current):
                    required = _lowest_plan_with_higher_cap(resource, current_cap=cap)
                    raise EntitlementError(
                        "cap_reached",
                        required_plan=required,
                        resource=resource,
                        cap=cap,
                        message=(f"You have reached the {resource} limit on your current plan."),
                    )

            return await func(*args, **kwargs)

        wrapper.__signature__ = _inject_entitlements_param(func, _CAP_KW)  # type: ignore[attr-defined]
        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _resolve_count(provider: CapCountProvider, org_id: uuid.UUID) -> int:
    """Invoke ``provider(org_id)``; await the result if it is awaitable."""
    result = provider(org_id)
    if inspect.isawaitable(result):
        result = await result
    return int(result)


def _inject_entitlements_param(func: Callable[..., Any], param_name: str) -> inspect.Signature:
    """Return ``func``'s signature with an ``Entitlements`` dependency parameter inserted.

    FastAPI inspects the wrapper's signature to discover dependencies.
    By inserting a keyword-only ``param_name: Entitlements =
    Depends(get_entitlements)`` parameter we get the bundle injected at
    call time without polluting the original handler's argument list.

    The parameter goes immediately before any ``**kwargs`` to keep the
    handler's signature stable for OpenAPI generation.
    """
    sig = inspect.signature(func)
    params = list(sig.parameters.values())
    new_param = inspect.Parameter(
        name=param_name,
        kind=inspect.Parameter.KEYWORD_ONLY,
        default=Depends(get_entitlements),
        annotation=Entitlements,
    )
    var_kw_index = next(
        (i for i, p in enumerate(params) if p.kind == inspect.Parameter.VAR_KEYWORD),
        len(params),
    )
    new_params = params[:var_kw_index] + [new_param] + params[var_kw_index:]
    return sig.replace(parameters=new_params)


__all__ = ["requires_feature", "enforces_cap", "CapCountProvider"]
