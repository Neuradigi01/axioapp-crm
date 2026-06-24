"""CLI — install a pack manifest into one org.

Usage:
    python -m src.app.scripts.install_pack \\
        --org demo \\
        --pack-file src/app/packs/furniture/pack.yaml

Or by registered template_id (the loader looks under
`src/app/packs/<template_id>/pack.yaml`):

    python -m src.app.scripts.install_pack --org demo --pack furniture

The script is idempotent — re-running it produces zero-write seconds
once the org is at the manifest's version.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path


from src.app.core.tenants import data_access
from src.app.core.packs.installer import install
from src.app.core.packs.loader import PackLoadError, load_pack
from src.app.shared.context import RequestContext, set_context
from src.app.shared.db import async_session


def _resolve_pack_file(template_id: str | None, pack_file: str | None) -> Path:
    if pack_file:
        return Path(pack_file)
    if not template_id:
        raise SystemExit(
            "Must pass either --pack-file or --pack <template_id>"
        )
    # Conventional location: src/app/packs/<template_id>/pack.yaml
    return Path("src/app/packs") / template_id / "pack.yaml"


async def _resolve_org(slug: str) -> uuid.UUID:
    async with async_session() as session:
        org = await data_access.get_organization_by_slug(session, slug)
        if org is None:
            raise SystemExit(f"organization '{slug}' not found")
        return org.id


async def _run(args: argparse.Namespace) -> int:
    pack_file = _resolve_pack_file(args.pack, args.pack_file)
    try:
        manifest = load_pack(pack_file)
    except PackLoadError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2

    org_id = await _resolve_org(args.org)

    # The installer uses `audit.log` which expects a tenant context.
    set_context(RequestContext(org_id=org_id))

    async with async_session() as session:
        report = await install(session, org_id=org_id, manifest=manifest)

    print(json.dumps(report.as_dict(), indent=2))
    return 0 if not report.errors else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install a FurnitureCRM pack manifest into an org."
    )
    parser.add_argument("--org", required=True, help="organisation slug")
    parser.add_argument(
        "--pack",
        help="template_id (resolves to src/app/packs/<id>/pack.yaml)",
    )
    parser.add_argument(
        "--pack-file", help="explicit path to a pack.yaml file"
    )
    args = parser.parse_args()
    exit_code = asyncio.run(_run(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
