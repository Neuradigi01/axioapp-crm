"""CLI sanity check for `plans.yaml`.

Usage:
    uv run python -m src.app.core.subscriptions.plans_cli validate

Exits 0 if the YAML loads and validates, prints `OK: N plans loaded.`
Exits 1 with a descriptive error on validation failure — CI runs this
to fail-fast before a malformed pricing change reaches deploy.
"""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import ValidationError

from src.app.core.subscriptions import plans


def _validate(path: Path | None = None) -> int:
    try:
        registry = plans.reload(path)
    except FileNotFoundError as exc:
        print(f"ERROR: plans.yaml not found at {exc.filename}", file=sys.stderr)
        return 1
    except ValidationError as exc:
        print(f"ERROR: plans.yaml failed validation:\n{exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"OK: {len(registry.plans)} plans loaded.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] != "validate":
        print("Usage: plans_cli.py validate [path-to-yaml]", file=sys.stderr)
        return 2

    path = Path(args[1]) if len(args) > 1 else None
    return _validate(path)


if __name__ == "__main__":
    raise SystemExit(main())
