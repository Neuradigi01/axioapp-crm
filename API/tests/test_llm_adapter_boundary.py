"""Boundary pin-test — ``openai`` may only be imported inside
``src/app/shared/llm/openai.py``.

Rationale: every provider-specific SDK gets a single adapter file
under ``shared/llm/``. Keeping the import contained means:

  * Rewiring to a proxy / mock in tests only needs to patch one file.
  * Future adapters (Anthropic, Google, OpenRouter) can't "leak"
    provider-specific concepts into the rest of the codebase.
  * SSRF defence stays airtight — the adapter file hardcodes
    ``base_url``; there's no way for a stray import elsewhere to
    smuggle in a custom base.

The test parses every ``.py`` under ``src/app/`` with ``ast`` — not
a text grep — so a comment ``# import openai`` doesn't false-positive.
Only real ``import openai`` / ``from openai …`` statements count.
"""

from __future__ import annotations

import ast
import pathlib

# Files allowed to import ``openai``. Extend deliberately.
_ALLOWED: set[str] = {
    "src/app/shared/llm/openai.py",
}

_APP_ROOT = pathlib.Path(__file__).resolve().parent.parent / "src" / "app"


def _imports_openai(source: str) -> bool:
    """Return True iff the file has any real ``import openai`` or
    ``from openai …`` statement. Comments + strings are ignored via
    ``ast`` parsing."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # Broken file — leave to ruff/pytest to flag; the boundary
        # test only cares about parse-able files.
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root == "openai":
                    return True
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            if root == "openai":
                return True
    return False


def _relative(path: pathlib.Path) -> str:
    """Return the path in ``src/app/...`` form for allow-list matching."""
    parts = path.resolve().parts
    if "src" in parts:
        i = parts.index("src")
        return "/".join(parts[i:])
    return str(path)


def test_openai_import_only_in_adapter() -> None:
    offenders: list[str] = []
    for py in _APP_ROOT.rglob("*.py"):
        rel = _relative(py)
        if rel in _ALLOWED:
            continue
        source = py.read_text(encoding="utf-8")
        if _imports_openai(source):
            offenders.append(rel)
    assert not offenders, (
        f"Only {sorted(_ALLOWED)} may import ``openai``. "
        f"Move provider-specific code into a new file under "
        f"shared/llm/ (matching adapter pattern) rather than "
        f"importing directly. Offending files: {offenders}"
    )


def test_pin_detects_direct_import() -> None:
    """Self-verification — the ``_imports_openai`` helper actually
    catches the two ban shapes (``import openai`` + ``from openai
    import …``)."""
    assert _imports_openai("import openai") is True
    assert _imports_openai("import openai as _openai") is True
    assert _imports_openai("from openai import AsyncOpenAI") is True
    assert _imports_openai("from openai.types import Whatever") is True


def test_pin_ignores_comments_and_strings() -> None:
    """A source file that only mentions ``openai`` in a comment or a
    string literal must NOT be flagged — that would false-positive
    the CLAUDE.md docs, spec MDs, and error messages that reference
    the SDK by name."""
    assert _imports_openai("# import openai here") is False
    assert _imports_openai("x = 'from openai import Foo'") is False
    assert _imports_openai('"""from openai import AsyncOpenAI"""') is False


def test_adapter_file_itself_imports_openai() -> None:
    """Sanity — the adapter file we allow-listed does in fact import
    ``openai``. If someone deletes the adapter, this test fails and
    flags the drift."""
    adapter = _APP_ROOT / "shared" / "llm" / "openai.py"
    assert adapter.exists(), "shared/llm/openai.py is missing"
    assert _imports_openai(adapter.read_text(encoding="utf-8")) is True
