"""Compliance footer builder.

Appends a small footer block to outbound HTML carrying:

  * sender's company / workspace name,
  * physical address (composed from `OrgSettings.address_line1/2,
    city, state, postal_code, country`),
  * an unsubscribe link.

CAN-SPAM (US) requires unsubscribe + physical address. India DPDP
2023 requires unsubscribe + sender identity. Both met by this footer
+ the `List-Unsubscribe` headers set by the email adapter.

Pure transform — same signature as `pixel.inject` / `link_rewriter.
rewrite` so the email adapter can compose them in a tidy sequence.
"""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid import cycle at module load.
    from src.app.core.settings.models import OrgSettings


_FOOTER_STYLE = (
    "font-family:Arial,Helvetica,sans-serif;font-size:11px;"
    "color:#888;margin-top:24px;padding-top:12px;"
    "border-top:1px solid #e5e7eb;line-height:1.5"
)


def _compose_address(settings: OrgSettings | None) -> str:
    """Build a comma-separated single-line address from the org's
    structured address fields. Returns empty string when no parts
    populated — the adapter rejects sends in that case (CAN-SPAM)."""
    if settings is None:
        return ""
    parts = [
        getattr(settings, "address_line1", None),
        getattr(settings, "address_line2", None),
        getattr(settings, "city", None),
        getattr(settings, "state", None),
        getattr(settings, "postal_code", None),
        getattr(settings, "country", None),
    ]
    return ", ".join(p for p in parts if p)


def build(
    *,
    org_name: str,
    org_settings: OrgSettings | None,
    unsubscribe_url: str,
) -> str:
    """Return the HTML fragment to append to outbound `body_html`.

    Always renders the unsubscribe link. The company name + address
    block is omitted when both `org_name` and the composed address
    are blank (the adapter still fails the send via its own validation
    in that case — this is belt-and-braces)."""
    address = _compose_address(org_settings)
    safe_name = escape(org_name or "")
    safe_address = escape(address)
    safe_unsub = escape(unsubscribe_url)
    identity_line = ""
    if safe_name or safe_address:
        identity_line = (
            f"<div>{safe_name}{' · ' if safe_name and safe_address else ''}{safe_address}</div>"
        )
    return (
        f'<div style="{_FOOTER_STYLE}">'
        f"{identity_line}"
        f'<div style="margin-top:6px;">'
        f'<a href="{safe_unsub}" '
        'style="color:#888;text-decoration:underline;">'
        "Unsubscribe</a> from these emails."
        "</div>"
        "</div>"
    )


def has_required_address(org_settings: OrgSettings | None) -> bool:
    """CAN-SPAM compliance gate: at least one address line must be set.

    The email adapter calls this before sending; sends fail-fast with
    a clear error when the org hasn't configured an address. Avoids
    silently shipping non-compliant mail."""
    return bool(_compose_address(org_settings))


def append(body_html: str, *, footer_html: str) -> str:
    """Append the footer just before `</body>` (or at end if absent)."""
    if not body_html:
        return f"<div>{footer_html}</div>"
    import re

    match = re.search(r"</\s*body\s*>", body_html, re.IGNORECASE)
    if match is None:
        return body_html + footer_html
    return body_html[: match.start()] + footer_html + body_html[match.start() :]


__all__ = ["append", "build", "has_required_address"]
