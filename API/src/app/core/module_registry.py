"""Module registry — rules 5 + 6 of the master prompt.

Every module (core or pack) optionally exposes a `module.py` exporting
a `MODULE: ModuleDescriptor` constant. On app startup the registry
walks `src.app.core.*` and `src.app.packs.*.modules.*`, imports each
`module.py` it finds, and collects the `MODULE` it exports.

Core never reaches into pack-specific code: the discovery walker only
looks for the conventional file name. Pack modules register THEMSELVES
when imported — core has no compile-time knowledge of what packs exist
(rule 1).

The same pass also registers each `MODULE.permissions` key into the
`permissions` table via `permissions.service.register_permissions` so
RBAC rows exist before any role tries to be granted them.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import pkgutil
import re
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Literal

logger = logging.getLogger(__name__)


_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_PERM_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")

Layer = Literal["core", "pack"]

# Packages the registry sweeps. Pack discovery walks
# `src.app.packs.<pack>.modules.*` — one level deeper than core so a
# pack's top-level `__init__.py` doesn't accidentally become a module.
_CORE_PACKAGE = "src.app.core"
_PACKS_PACKAGE = "src.app.packs"


@dataclass(frozen=True, slots=True)
class ModuleDescriptor:
    """One row in the registry.

    `route` is the backend mount point (`/api/v1/...`); `frontend_route`
    is what the SPA sidebar uses. `menu_position` orders the sidebar
    (lower = higher). `parent` lets a module nest under another
    module's id for grouped menus.

    `always_visible=True` is for modules that contain at least one
    sub-page reachable by every authenticated user (e.g. Settings hosts
    the per-user Notifications preferences tab). The module's declared
    permissions still get registered into the `permissions` table for
    role seeding — `always_visible` only short-circuits the sidebar
    visibility check.
    """

    id: str
    name: str
    icon: str
    layer: Layer
    route: str
    frontend_route: str
    permissions: list[str] = field(default_factory=list)
    menu_position: int | None = 100
    parent: str | None = None
    always_visible: bool = False
    # Auto-populated by `discover_modules` for pack modules (extracted
    # from the import path `src.app.packs.<pack_id>.modules.<mod>`).
    # None for core modules. Filtered against `org.template_id` in
    # `list_for_user` so pack modules never render on orgs that haven't
    # installed the pack — even if stray permission rows exist.
    pack_id: str | None = None

    def __post_init__(self) -> None:
        if not _ID_RE.match(self.id):
            raise ValueError(f"ModuleDescriptor.id {self.id!r} must match [a-z][a-z0-9_]*")
        if not self.route.startswith("/"):
            raise ValueError(f"ModuleDescriptor.route {self.route!r} must start with '/'")
        if not self.frontend_route.startswith("/"):
            raise ValueError(
                f"ModuleDescriptor.frontend_route {self.frontend_route!r} must start with '/'"
            )
        if self.layer not in ("core", "pack"):
            raise ValueError(f"ModuleDescriptor.layer {self.layer!r} must be 'core' or 'pack'")
        for key in self.permissions:
            if not _PERM_RE.match(key):
                raise ValueError(f"permission key {key!r} must match '<module>.<action>'")


class ModuleRegistry:
    """In-memory registry. One instance, lives in this module's globals."""

    def __init__(self) -> None:
        self._modules: dict[str, ModuleDescriptor] = {}

    def register(self, descriptor: ModuleDescriptor) -> None:
        if descriptor.id in self._modules:
            raise ValueError(f"module {descriptor.id!r} is already registered")
        self._modules[descriptor.id] = descriptor

    def get(self, module_id: str) -> ModuleDescriptor | None:
        return self._modules.get(module_id)

    def list(self) -> list[ModuleDescriptor]:
        """All registered modules, sorted by `(menu_position, id)`.

        `menu_position=None` denotes a hidden module (no sidebar entry);
        it sorts to the end while still being discoverable so its
        permissions register on startup.
        """
        return sorted(
            self._modules.values(),
            key=lambda m: (
                m.menu_position if m.menu_position is not None else float("inf"),
                m.id,
            ),
        )

    def list_for_user(
        self,
        granted: Iterable[str],
        *,
        org_template_id: str | None = None,
    ) -> list[ModuleDescriptor]:
        """Return modules the user holds at least one declared permission for.

        Modules that declare an empty permission list — or set
        `always_visible=True` — are public and always returned. Modules
        with `menu_position=None` are excluded — they exist in the
        registry for permission discovery only and do not render in the
        sidebar (they surface from within other UIs, e.g. Settings).

        Pack modules (`pack_id is not None`) additionally require the
        caller's org to be on that pack — `pack_id == org_template_id`.
        This is the second gate that keeps a leaked permission grant
        (e.g. someone ran the real_estate installer against a base-pack
        org) from surfacing pack UI on the wrong tenant. Passing
        `org_template_id=None` disables the tenant gate (used only by
        tests that pre-date the gate).
        """
        granted_set = set(granted)
        result: list[ModuleDescriptor] = []
        for m in self.list():
            if m.menu_position is None:
                continue
            if (
                m.pack_id is not None
                and org_template_id is not None
                and m.pack_id != org_template_id
            ):
                continue
            if not (
                m.always_visible
                or not m.permissions
                or any(p in granted_set for p in m.permissions)
            ):
                continue
            result.append(m)
        return result

    def clear(self) -> None:
        """Wipe the registry (used by tests and the dev refresh endpoint)."""
        self._modules.clear()


registry = ModuleRegistry()


def _walk_module_files(parent_package: str) -> list[str]:
    """Return import paths of every `<parent>.<sub>.module` that exists.

    Walks one level of children under `parent_package` (so for packs
    that means `src.app.packs.<pack>` — pack discovery recurses into
    `.modules` separately).
    """
    try:
        parent = importlib.import_module(parent_package)
    except ModuleNotFoundError:
        return []

    found: list[str] = []
    for info in pkgutil.iter_modules(parent.__path__, prefix=f"{parent_package}."):
        if not info.ispkg:
            continue
        candidate = f"{info.name}.module"
        try:
            importlib.import_module(candidate)
        except ModuleNotFoundError:
            continue
        except Exception:
            logger.exception("failed importing %s", candidate)
            continue
        found.append(candidate)
    return found


def _walk_pack_module_files() -> list[str]:
    """Each pack lives at `src.app.packs.<pack>/modules/<mod>/module.py`.

    The discovery walker steps into every `<pack>/modules/<mod>` it
    finds and tries to import `module.py`.
    """
    try:
        packs = importlib.import_module(_PACKS_PACKAGE)
    except ModuleNotFoundError:
        return []

    found: list[str] = []
    for pack_info in pkgutil.iter_modules(packs.__path__, prefix=f"{_PACKS_PACKAGE}."):
        if not pack_info.ispkg:
            continue
        modules_pkg_name = f"{pack_info.name}.modules"
        try:
            modules_pkg = importlib.import_module(modules_pkg_name)
        except ModuleNotFoundError:
            continue
        for mod_info in pkgutil.iter_modules(modules_pkg.__path__, prefix=f"{modules_pkg_name}."):
            if not mod_info.ispkg:
                continue
            candidate = f"{mod_info.name}.module"
            try:
                importlib.import_module(candidate)
            except ModuleNotFoundError:
                continue
            except Exception:
                logger.exception("failed importing %s", candidate)
                continue
            found.append(candidate)
    return found


def _extract_pack_id(path: str) -> str | None:
    """Return the pack slug for a pack-module import path, else None.

    Pack modules live at `src.app.packs.<pack_id>.modules.<mod>.module`
    — the pack slug is the 4th dotted segment (index 3). Core modules
    (`src.app.core.<mod>.module`) get `None`.
    """
    parts = path.split(".")
    if len(parts) >= 5 and parts[:3] == ["src", "app", "packs"]:
        return parts[3]
    return None


def _walk_pack_event_catalog_files() -> list[tuple[str, str]]:
    """Every pack's ``event_catalog.py`` files paired with the
    pack slug that owns them (``tasks/automation-conditions/``
    Step 7).

    Looks in two places per pack:
      * ``src.app.packs.<pack>.event_catalog`` — pack-level file for
        events that span multiple pack modules.
      * ``src.app.packs.<pack>.modules.<mod>.event_catalog`` —
        module-level file for events scoped to one pack module.

    A pack can use either or both. Missing files are silently
    skipped (``ModuleNotFoundError``) since ``event_catalog.py``
    is optional — a pack that doesn't publish any custom events
    just doesn't register.
    """
    try:
        packs = importlib.import_module(_PACKS_PACKAGE)
    except ModuleNotFoundError:
        return []

    found: list[tuple[str, str]] = []
    for pack_info in pkgutil.iter_modules(packs.__path__, prefix=f"{_PACKS_PACKAGE}."):
        if not pack_info.ispkg:
            continue
        pack_id = pack_info.name.rsplit(".", 1)[-1]
        # Pack-level event_catalog.py (optional). find_spec returns
        # None when the child module doesn't exist; only raises when
        # the parent is unimportable (already handled by the outer
        # iter_modules walk).
        pack_level = f"{pack_info.name}.event_catalog"
        try:
            spec = importlib.util.find_spec(pack_level)
        except (ModuleNotFoundError, ImportError):
            spec = None
        if spec is not None:
            found.append((pack_level, pack_id))
        # Per-module event_catalog.py files.
        modules_pkg_name = f"{pack_info.name}.modules"
        try:
            modules_pkg = importlib.import_module(modules_pkg_name)
        except ModuleNotFoundError:
            continue
        for mod_info in pkgutil.iter_modules(modules_pkg.__path__, prefix=f"{modules_pkg_name}."):
            if not mod_info.ispkg:
                continue
            candidate = f"{mod_info.name}.event_catalog"
            try:
                spec = importlib.util.find_spec(candidate)
            except (ModuleNotFoundError, ImportError):
                spec = None
            if spec is not None:
                found.append((candidate, pack_id))
    return found


def _import_pack_event_catalogs() -> None:
    """Import every pack's ``event_catalog.py`` inside a pack-scoped
    ContextVar so registrations auto-tag with the pack slug.

    Import failures re-raise so a broken pack fails app startup
    loud — a silently-missing pack section in the automation
    picker would confuse operators without any actionable signal.
    """
    from src.app.core.automation._pack_context import (
        reset_current_pack,
        set_current_pack,
    )

    for path, pack_id in _walk_pack_event_catalog_files():
        token = set_current_pack(pack_id)
        try:
            importlib.import_module(path)
        except Exception:
            logger.exception(
                "failed importing pack event_catalog %s (pack=%s) — app startup will fail",
                path,
                pack_id,
            )
            reset_current_pack(token)
            raise
        else:
            reset_current_pack(token)


def discover_modules() -> list[ModuleDescriptor]:
    """Find every `module.py` under core + packs, register their MODULEs.

    Also imports every pack's ``event_catalog.py`` (``tasks/automation-
    conditions/`` Step 7) inside a pack-scoped ContextVar so the
    automation catalog + resolver registries pick up pack-owned
    entries with the correct ``pack_id`` for tenant filtering.

    Idempotent: callers (lifespan + dev refresh endpoint) `clear()`
    first, then call this. Returns the registered descriptors in
    registry order. Pack modules get their `pack_id` auto-populated
    from the import path so the sidebar filter can gate them by
    `org.template_id` without each module needing to declare it.
    """
    paths = _walk_module_files(_CORE_PACKAGE) + _walk_pack_module_files()
    for path in paths:
        mod = importlib.import_module(path)
        descriptor = getattr(mod, "MODULE", None)
        if descriptor is None:
            continue
        if not isinstance(descriptor, ModuleDescriptor):
            logger.warning(
                "%s exports MODULE but it's not a ModuleDescriptor (got %r)",
                path,
                type(descriptor).__name__,
            )
            continue
        pack_id = _extract_pack_id(path)
        if pack_id is not None and descriptor.pack_id != pack_id:
            descriptor = replace(descriptor, pack_id=pack_id)
        registry.register(descriptor)
    _import_pack_event_catalogs()
    return registry.list()
