"""HTML sanitiser + plain-text deriver for Email templates.

Campaigns v1 Step 04 — Email templates can now carry a ``body_html``
field authored via the composer. Any HTML we accept from the frontend
is untrusted (the composer is a ``contenteditable`` div — anything can
end up in the DOM) so this module is the security boundary between
inbound HTML and the database.

Two entry points:

  * :func:`sanitize_email_html` — bleach-based tag/attribute allow-list.
    Strips ``<script>``, ``<iframe>``, ``<object>``, event handlers
    (``onload`` / ``onclick`` / etc.), ``javascript:`` URLs, and any
    tag / attribute not on the allow list. Leaves merge-tag placeholders
    (``{{first_name}}``) untouched — bleach treats them as text.
  * :func:`derive_plain_text` — strips every tag and normalises
    whitespace to produce a Gmail-multipart plain-text fallback. Kept
    small on purpose (no ``html2text`` dep): reuses bleach's strip mode
    so we don't ship a second HTML parser.

Both functions are pure; no DB, no request context. Callable from the
service layer OR from tests without any fixture.
"""

from __future__ import annotations

import re

import bleach
from bleach.css_sanitizer import CSSSanitizer

# --- Allow lists -----------------------------------------------------------

_ALLOWED_TAGS: frozenset[str] = frozenset(
    {
        "a",
        "b",
        "blockquote",
        "br",
        "code",
        "div",
        "em",
        "h1",
        "h2",
        "h3",
        "h4",
        "hr",
        "i",
        "img",
        "li",
        "ol",
        "p",
        "pre",
        "s",
        "span",
        "strong",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "u",
        "ul",
    }
)

_ALLOWED_ATTRS: dict[str, list[str]] = {
    "*": ["style", "class"],
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "width", "height"],
    "table": ["width", "border", "cellpadding", "cellspacing"],
    "td": ["colspan", "rowspan", "width", "align", "valign"],
    "th": ["colspan", "rowspan", "width", "align", "valign"],
}

_ALLOWED_PROTOCOLS: list[str] = ["http", "https", "mailto"]

_ALLOWED_CSS_PROPERTIES: frozenset[str] = frozenset(
    {
        "background-color",
        "border",
        "border-color",
        "border-radius",
        "border-style",
        "border-width",
        "color",
        "font-family",
        "font-size",
        "font-style",
        "font-weight",
        "line-height",
        "margin",
        "margin-bottom",
        "margin-left",
        "margin-right",
        "margin-top",
        "padding",
        "padding-bottom",
        "padding-left",
        "padding-right",
        "padding-top",
        "text-align",
        "text-decoration",
        "width",
    }
)

_CSS_SANITIZER = CSSSanitizer(allowed_css_properties=list(_ALLOWED_CSS_PROPERTIES))


# --- Public API ------------------------------------------------------------


def sanitize_email_html(html: str) -> str:
    """Return an XSS-safe HTML string.

    Uses bleach's tag + attribute allow list; every ``<script>``,
    ``<iframe>``, ``<object>``, event handler, and ``javascript:`` URL
    is stripped verbatim. Merge-tag placeholders (``{{first_name}}``)
    look like plain text to bleach and pass through unchanged.

    ``strip=True`` removes disallowed tags without leaking the raw
    markup — an ``<script>alert(1)</script>`` becomes an empty string,
    not an escaped ``&lt;script&gt;``.
    """
    if not html:
        return ""
    return bleach.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        protocols=_ALLOWED_PROTOCOLS,
        css_sanitizer=_CSS_SANITIZER,
        strip=True,
        strip_comments=True,
    )


_MULTISPACE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def derive_plain_text(html: str) -> str:
    """Return a Gmail-multipart plain-text fallback for ``html``.

    Strips every tag (bleach ``tags=[]`` + ``strip=True``) and collapses
    runs of whitespace so the output looks reasonable in a mail client
    that can't render HTML. Block-level tags are replaced with newlines
    before stripping so paragraph structure survives.
    """
    if not html:
        return ""
    # Preserve paragraph structure by injecting a newline before common
    # block-level closers. bleach flattens everything to inline text
    # otherwise, and Gmail's plain-text fallback would show a wall of
    # words.
    with_breaks = re.sub(
        r"</\s*(?:p|div|br|h[1-4]|li|tr|blockquote)\s*/?>",
        "\n",
        html,
        flags=re.IGNORECASE,
    )
    stripped = bleach.clean(with_breaks, tags=[], attributes={}, strip=True)
    unescaped = (
        stripped.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    collapsed = _MULTISPACE.sub(" ", unescaped)
    normalised = _BLANK_LINES.sub("\n\n", collapsed).strip()
    return normalised


__all__ = ["sanitize_email_html", "derive_plain_text"]
