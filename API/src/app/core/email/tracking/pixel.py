"""Pixel injection — pure transform.

`inject(body_html, token, base_url)` appends a 1×1 tracking image to
the HTML body. Placement rules:

  * If `</body>` exists (case-insensitive), insert immediately before it.
  * Otherwise, append to the end of the HTML.

The `<img>` is `width="1" height="1"` with a transparent border and
the rendered HTML attribute `alt=""` so accessibility tools skip it.
Modern image-blocking clients (Outlook desktop default) won't fetch
the URL — that's the well-known noise floor on email-open metrics.

No new dependency: stdlib regex is enough since `</body>` is a fixed
literal we only need to locate, not parse.
"""
from __future__ import annotations

import re


_BODY_CLOSE_RE = re.compile(r"</\s*body\s*>", re.IGNORECASE)


def _pixel_tag(open_url: str) -> str:
    """One-line tag — `width`/`height` are HTML attributes (no CSS)
    so it renders consistently even when the client strips style."""
    return (
        f'<img src="{open_url}" width="1" height="1" '
        'border="0" alt="" style="display:block;border:0;'
        'outline:none;text-decoration:none;height:1px;width:1px;" />'
    )


def inject(body_html: str, *, token: str, base_url: str) -> str:
    """Return `body_html` with the 1×1 tracking image appended.

    `base_url` is the public tracking host (no trailing slash) — the
    final pixel URL is `{base_url}/api/v1/track/o/{token}`. Empty
    `body_html` returns the bare pixel wrapped in a `<div>` so the
    HTML alternative isn't degenerate.
    """
    open_url = f"{base_url.rstrip('/')}/api/v1/track/o/{token}"
    tag = _pixel_tag(open_url)
    if not body_html:
        return f"<div>{tag}</div>"
    match = _BODY_CLOSE_RE.search(body_html)
    if match is None:
        return body_html + tag
    return body_html[: match.start()] + tag + body_html[match.start() :]


__all__ = ["inject"]
