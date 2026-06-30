"""Link rewriter — rewrite every `<a href="…">` to route through the
click redirector, preserving the original URL inside the redirect.

Pure transform: `rewrite(body_html, token, base_url)` returns the
modified HTML. Skips:

  * `mailto:` — directly opens the recipient's mail client.
  * `tel:`    — phone dial intent.
  * `data:`   — inline data URIs.
  * `sms:`    — SMS intent.
  * `#`-only anchors — in-document fragments.
  * URLs that already point at our own `/api/v1/track/` redirector
    (idempotency: re-running the pipeline is a no-op).

Strategy:

  * Find every `<a … href="X" …>` (single or double-quoted) via a
    targeted regex. We don't need a full HTML parser — the only
    thing we mutate is the `href` value, and the project deliberately
    avoids new HTML-parser dependencies (see Step 6 for the same
    reasoning around html2text).

  * `X` is base64-url-encoded and appended as `?u=` so the click
    handler can decode the target without storing it server-side.
"""

from __future__ import annotations

import base64
import re

# Matches `<a … href="X" …>` or `<a … href='X' …>`. Greedy `[^"']*`
# stops at the matching quote so we don't span the next href on a
# multi-link document. The whole-tag span is captured as group(0)
# and the href value as group(2) (group 1 is the quote char).
_HREF_RE = re.compile(
    r"""(?ix)
    (<a\b[^>]*?\shref=)        # group 1: `<a ... href=`
    (["'])                     # group 2: opening quote
    (?P<url>[^"'>]+)           # named group: the URL
    (\2)                       # group 4: closing quote (same as group 2)
    """,
    re.VERBOSE,
)


def _should_skip(url: str, *, tracker_prefix: str) -> bool:
    """Return True for URLs the rewriter must NOT touch."""
    if not url:
        return True
    stripped = url.strip()
    if not stripped:
        return True
    lower = stripped.lower()
    if lower.startswith(("mailto:", "tel:", "sms:", "data:", "javascript:")):
        return True
    if stripped.startswith("#"):
        return True
    # Idempotency: don't double-wrap our own tracker.
    if stripped.startswith(tracker_prefix):
        return True
    return False


def _b64url(raw: str) -> str:
    return base64.urlsafe_b64encode(raw.encode("utf-8")).rstrip(b"=").decode("ascii")


def rewrite(body_html: str, *, token: str, base_url: str) -> str:
    """Return `body_html` with every eligible `<a href>` rewritten to
    route through the click redirector.

    `token` is the message-scoped HMAC token; `base_url` is the public
    tracking host (no trailing slash). The click URL is
    `{base_url}/api/v1/track/c/{token}?u={base64url(original_href)}`.

    Idempotent: re-running on already-rewritten HTML doesn't double-
    wrap (already-tracker URLs are skipped).
    """
    if not body_html:
        return body_html
    base = base_url.rstrip("/")
    tracker_prefix = f"{base}/api/v1/track/"
    click_root = f"{base}/api/v1/track/c/{token}"

    def _rewrite_match(m: re.Match[str]) -> str:
        original = m.group("url")
        if _should_skip(original, tracker_prefix=tracker_prefix):
            return m.group(0)
        encoded = _b64url(original)
        replacement = f"{click_root}?u={encoded}"
        # Reconstruct the tag with the rewritten href; keep the same
        # quote character so we don't accidentally break a single-
        # quoted attribute.
        return f"{m.group(1)}{m.group(2)}{replacement}{m.group(4)}"

    return _HREF_RE.sub(_rewrite_match, body_html)


__all__ = ["rewrite"]
