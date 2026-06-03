"""Pack catalog composition.

`get_catalog()` returns the ordered list of `CatalogTile` for the
onboarding picker. It composes from two sources:

1. **`catalog_config.CATALOG_PACKS`** — tile metadata (name, description,
   icon, modules preview, display order) for every pack we want to
   show, real or placeholder.
2. **`src/app/packs/*/pack.yaml`** — every subfolder containing a
   `pack.yaml` is considered "real" (installable today). Its `pack_id`
   matches the on-disk manifest's `pack_id` field, not the folder name.

A tile is marked `status="available"` if its `pack_id` matches a real
pack, else `status="coming_soon"`. The result is sorted ascending by
`display_order`.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from src.app.core.packs.catalog_config import CATALOG_PACKS
from src.app.core.packs.loader import PackLoadError, load_pack
from src.app.core.packs.schemas import CatalogResponse, CatalogTile

# Directory holding pack subfolders, each with its own pack.yaml.
# This file lives at src/app/core/packs/service.py; packs/ is at
# src/app/packs/, two levels up from `core/packs/`.
_PACKS_DIR = Path(__file__).resolve().parents[2] / "packs"


def _discover_real_pack_ids() -> set[str]:
    """Scan `src/app/packs/*/pack.yaml` and return the set of pack_ids
    found. Loader errors on a single manifest are skipped — one broken
    pack must not hide the rest of the catalog. A pack that fails to
    load is also un-installable, so its tile correctly stays out of the
    "available" set.
    """
    found: set[str] = set()
    if not _PACKS_DIR.exists():
        return found
    for child in _PACKS_DIR.iterdir():
        if not child.is_dir():
            continue
        manifest_path = child / "pack.yaml"
        if not manifest_path.is_file():
            continue
        try:
            manifest = load_pack(manifest_path)
        except PackLoadError:
            continue
        found.add(manifest.pack_id)
    return found


@lru_cache(maxsize=1)
def get_catalog() -> CatalogResponse:
    """Build the catalog response.

    Cached for the lifetime of the process — the config list and the
    on-disk manifest set are both static at startup. Tests can call
    `get_catalog.cache_clear()` between cases.
    """
    real_ids = _discover_real_pack_ids()
    tiles = [
        CatalogTile(
            pack_id=entry["pack_id"],
            name=entry["name"],
            description=entry["description"],
            icon=entry["icon"],
            status=(
                "available" if entry["pack_id"] in real_ids else "coming_soon"
            ),
            default_currency=entry["default_currency"],
            default_tax_rate=entry["default_tax_rate"],
            modules_preview=list(entry["modules_preview"]),
            display_order=entry["display_order"],
        )
        for entry in CATALOG_PACKS
    ]
    tiles.sort(key=lambda t: t.display_order)
    return CatalogResponse(packs=tiles)


__all__ = ["get_catalog"]
