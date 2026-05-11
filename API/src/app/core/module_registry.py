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
import logging
import pkgutil
import re
from dataclasses import dataclass, field
from typing import Iterable, Literal

logger = logging.getLogger(__name__)


_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_PERM_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")

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
    """

    id: str
    name: str
    icon: str
    layer: Layer
    route: str
    frontend_route: str
    permissions: list[str] = field(default_factory=list)
    menu_position: int = 100
    parent: str | None = None

    def __post_init__(self) -> None:
        if not _ID_RE.match(self.id):
            raise ValueError(
                f"ModuleDescriptor.id {self.id!r} must match [a-z][a-z0-9_]*"
            )
        if not self.route.startswith("/"):
            raise ValueError(
                f"ModuleDescriptor.route {self.route!r} must start with '/'"
            )
        if not self.frontend_route.startswith("/"):
            raise ValueError(
                f"ModuleDescriptor.frontend_route {self.frontend_route!r} must start with '/'"
            )
        if self.layer not in ("core", "pack"):
            raise ValueError(
                f"ModuleDescriptor.layer {self.layer!r} must be 'core' or 'pack'"
            )
        for key in self.permissions:
            if not _PERM_RE.match(key):
                raise ValueError(
                    f"permission key {key!r} must match '<module>.<action>'"
                )


class ModuleRegistry:
    """In-memory registry. One instance, lives in this module's globals."""

    def __init__(self) -> None:
        self._modules: dict[str, ModuleDescriptor] = {}

    def register(self, descriptor: ModuleDescriptor) -> None:
        if descriptor.id in self._modules:
            raise ValueError(
                f"module {descriptor.id!r} is already registered"
            )
        self._modules[descriptor.id] = descriptor

    def get(self, module_id: str) -> ModuleDescriptor | None:
        return self._modules.get(module_id)

    def list(self) -> list[ModuleDescriptor]:
        """All registered modules, sorted by `(menu_position, id)`."""
        return sorted(
            self._modules.values(), key=lambda m: (m.menu_position, m.id)
        )

    def list_for_user(self, granted: Iterable[str]) -> list[ModuleDescriptor]:
        """Return modules the user holds at least one declared permission for.

        Modules that declare an empty permission list are public and
        always returned.
        """
        granted_set = set(granted)
        return [
            m
            for m in self.list()
            if not m.permissions or any(p in granted_set for p in m.permissions)
        ]

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
        for mod_info in pkgutil.iter_modules(
            modules_pkg.__path__, prefix=f"{modules_pkg_name}."
        ):
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


def discover_modules() -> list[ModuleDescriptor]:
    """Find every `module.py` under core + packs, register their MODULEs.

    Idempotent: callers (lifespan + dev refresh endpoint) `clear()`
    first, then call this. Returns the registered descriptors in
    registry order.
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
        registry.register(descriptor)
    return registry.list()
