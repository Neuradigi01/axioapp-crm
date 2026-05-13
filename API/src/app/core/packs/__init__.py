"""Pack-manifest infrastructure.

Re-exports the loader + installer entry points so other modules can
`from src.app.core.packs import load_pack, install`.
"""
from src.app.core.packs.installer import InstallReport, install
from src.app.core.packs.loader import PackLoadError, load_pack, load_pack_dict
from src.app.core.packs.manifest import PackManifest

__all__ = [
    "InstallReport",
    "PackLoadError",
    "PackManifest",
    "install",
    "load_pack",
    "load_pack_dict",
]
