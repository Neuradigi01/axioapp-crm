"""Pack-manifest infrastructure.

Re-exports the loader + installer + catalog entry points so other
modules can `from src.app.core.packs import load_pack, install,
get_catalog`.
"""
from src.app.core.packs.installer import InstallReport, install
from src.app.core.packs.loader import PackLoadError, load_pack, load_pack_dict
from src.app.core.packs.manifest import PackManifest
from src.app.core.packs.service import get_catalog

__all__ = [
    "InstallReport",
    "PackLoadError",
    "PackManifest",
    "get_catalog",
    "install",
    "load_pack",
    "load_pack_dict",
]
