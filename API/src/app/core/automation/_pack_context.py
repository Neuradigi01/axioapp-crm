"""Pack-scoped import context for the automation registries
(``tasks/automation-conditions/`` Step 7).

When the module-registry walker imports a pack's
``event_catalog.py``, every ``register_event`` / ``register_field_resolver``
call that runs during that import needs to know which pack it's
being registered under so the caller can filter the response by
the caller org's ``template_id``.

Rather than force each pack file to hardcode its own pack_id in
every register call, the walker sets a ContextVar to the pack slug
before ``importlib.import_module`` and resets it afterward. The
public register APIs read the ContextVar and auto-tag entries
with the pack slug when it's set.

Same pattern the tenant-context uses in :mod:`shared.context` for
RLS scoping — one thread-local knob that the framework layer
manages so leaf code doesn't have to.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

_CURRENT_PACK: ContextVar[str | None] = ContextVar("_automation_current_pack", default=None)


def set_current_pack(pack_id: str | None) -> Token[str | None]:
    """Set the current pack context. Walker calls this before
    importing a pack's ``event_catalog.py``. Returns a token the
    walker must pass to :func:`reset_current_pack` in the ``finally``
    of a try/finally, so an exception mid-import doesn't leak the
    pack context into subsequent imports."""
    return _CURRENT_PACK.set(pack_id)


def reset_current_pack(token: Token[str | None]) -> None:
    """Reset to the pack context that was active before the matching
    :func:`set_current_pack` call. Idempotent for a fresh token."""
    _CURRENT_PACK.reset(token)


def get_current_pack() -> str | None:
    """Return the pack slug currently importing, or ``None`` when
    no pack import is in flight (i.e. core registrations). Read by
    ``register_event`` / ``register_field_resolver`` to auto-tag
    entries with the caller's pack_id."""
    return _CURRENT_PACK.get()


__all__ = [
    "get_current_pack",
    "reset_current_pack",
    "set_current_pack",
]
