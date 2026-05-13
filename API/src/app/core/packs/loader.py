"""YAML loader for pack manifests.

`load_pack(path)` reads a YAML file, parses it, validates against
`PackManifest`, and returns the typed result. Errors include a
file-relative line number when the YAML parser provides one; schema
errors include the offending field path.

`load_pack_dict(data)` is a thin helper for tests that already have
the dict in memory.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from src.app.core.packs.manifest import PackManifest


class PackLoadError(Exception):
    """Raised for any YAML-parse or schema-validation failure."""


def load_pack(path: str | Path) -> PackManifest:
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise PackLoadError(f"could not read pack file {p}: {exc}") from exc

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        # PyYAML exceptions carry .problem_mark with line/column.
        mark = getattr(exc, "problem_mark", None)
        loc = (
            f" at line {mark.line + 1} col {mark.column + 1}"
            if mark is not None
            else ""
        )
        raise PackLoadError(
            f"YAML parse error in {p}{loc}: {exc}"
        ) from exc

    return load_pack_dict(data, source=str(p))


def load_pack_dict(
    data: Any, *, source: str = "<dict>"
) -> PackManifest:
    if not isinstance(data, dict):
        raise PackLoadError(
            f"{source}: top-level YAML must be a mapping, got {type(data).__name__}"
        )
    try:
        return PackManifest.model_validate(data)
    except ValidationError as exc:
        raise PackLoadError(
            f"{source}: schema validation failed:\n{exc}"
        ) from exc


__all__ = ["PackLoadError", "load_pack", "load_pack_dict"]
