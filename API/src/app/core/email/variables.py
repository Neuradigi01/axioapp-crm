"""Hand-rolled variable substitution for email templates.

The use case is narrow: substitute `{{ contact.first_name }}` style
dot-paths against a precomputed nested-dict context. No conditionals,
no loops, no inheritance — just safe interpolation.

Why not Jinja2:
  - Jinja2 isn't in our requirements.txt and pulling it in for this
    one use case adds a meaningful attack surface (sandbox escapes
    are a recurring Jinja2 issue: CVE-2024-22195, CVE-2024-34064).
  - The spec explicitly rejects `{% ... %}` constructs anyway. A
    50-line custom engine is more auditable and more secure.

The engine ships three public operations:

  - `extract_variable_paths(text) -> list[str]` — scan the body for
    every `{{ a.b.c }}` token, return sorted unique dot-paths. Used
    at save time so the editor can render its sidebar without re-
    parsing on every keystroke.
  - `reject_jinja_statements(text) -> None` — raise
    `TemplateSyntaxError` if any `{% ... %}` or `{# ... #}` tokens
    are present. Defends against operators pasting in Jinja-style
    conditionals that we don't support and don't render correctly.
  - `render(text, context, *, autoescape=True) -> str` — substitute
    every dot-path against `context` (a nested dict). Missing
    variables raise `MissingVariable(paths=[...])` so the router
    can return a precise 400. HTML autoescape protects against
    user-supplied content sneaking script tags into the rendered
    body.
"""
from __future__ import annotations

import html
import re
from typing import Any


# Variable token: `{{ a.b.c }}`. Spaces tolerated inside; the path
# is lowercase + underscores, dot-separated. Greedy on whitespace
# but strict on the path shape so a stray `{` doesn't get eaten.
_VAR_TOKEN_RE = re.compile(
    r"\{\{\s*([a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)*)\s*\}\}"
)

# Forbidden constructs: Jinja statements (`{% ... %}`) and comments
# (`{# ... #}`). Either triggers a save-time rejection.
_JINJA_STATEMENT_RE = re.compile(r"\{%.+?%\}", re.DOTALL)
_JINJA_COMMENT_RE = re.compile(r"\{#.+?#\}", re.DOTALL)


class TemplateSyntaxError(ValueError):
    """Raised when the template uses an unsupported construct
    (`{% ... %}` / `{# ... #}`) or an unrecognised variable shape."""


class MissingVariable(ValueError):
    """Raised by `render` when one or more variable paths cannot be
    resolved against the context. `paths` carries every missing
    dot-path so the router can list them in a 400."""

    def __init__(self, paths: list[str]) -> None:
        super().__init__(f"Missing variables: {', '.join(paths)}")
        self.paths: list[str] = list(paths)


def extract_variable_paths(text: str) -> list[str]:
    """Return every dot-path referenced in `text`, sorted + unique.
    `{{ contact.first_name }} … {{ lead.value }} … {{ contact.first_name }}`
    → `['contact.first_name', 'lead.value']`."""
    if not text:
        return []
    return sorted({match.group(1) for match in _VAR_TOKEN_RE.finditer(text)})


def reject_jinja_statements(text: str) -> None:
    """Validate at save time that `text` carries no `{% ... %}` /
    `{# ... #}` constructs. Raises `TemplateSyntaxError`."""
    if not text:
        return
    if _JINJA_STATEMENT_RE.search(text):
        raise TemplateSyntaxError(
            "Templates do not support `{% ... %}` constructs "
            "(if / for / block / include). Use plain "
            "`{{ contact.first_name }}` substitutions only."
        )
    if _JINJA_COMMENT_RE.search(text):
        raise TemplateSyntaxError(
            "Templates do not support `{# ... #}` comments. "
            "Strip them before saving."
        )


def _resolve_path(context: dict[str, Any], path: str) -> Any:
    """Walk a dot-path through nested dicts. Returns `_MISSING` when
    any segment is absent so the caller can list missing variables."""
    current: Any = context
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return _MISSING
        current = current[segment]
    return current


# Sentinel — distinguishable from None, which is a legitimate
# context value (e.g. `contact.last_name` may legitimately be None
# for a single-name contact; we still substitute "").
_MISSING = object()


def render(
    text: str,
    context: dict[str, Any],
    *,
    autoescape: bool = True,
) -> str:
    """Substitute every `{{ path }}` token against `context`.

    `autoescape=True` HTML-escapes substituted values so user-typed
    content can't inject script tags into the rendered body. Pass
    `autoescape=False` for the plain-text rendering path where
    `&amp;` etc. would be undesirable.

    Raises `MissingVariable` listing every path that couldn't be
    resolved. The router converts that to 400."""
    if not text:
        return ""

    # Reject `{% %}` / `{# #}` at render time too — belt-and-braces
    # in case a future code path skips the save-time validator.
    reject_jinja_statements(text)

    missing: list[str] = []

    def _sub(match: re.Match[str]) -> str:
        path = match.group(1)
        value = _resolve_path(context, path)
        if value is _MISSING:
            missing.append(path)
            return ""
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        rendered = str(value)
        return html.escape(rendered, quote=True) if autoescape else rendered

    output = _VAR_TOKEN_RE.sub(_sub, text)
    if missing:
        raise MissingVariable(sorted(set(missing)))
    return output


__all__ = [
    "MissingVariable",
    "TemplateSyntaxError",
    "extract_variable_paths",
    "reject_jinja_statements",
    "render",
]
