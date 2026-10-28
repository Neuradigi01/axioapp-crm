"""QR code rendering for quick-contact links
(whatsapp-platform-upgrade Step 26).

Server-side render using the ``qrcode`` library (already a dep —
see ``requirements.txt``). PNG output uses Pillow under the hood;
SVG is a pure-Python emitter from ``qrcode.image.svg``.

The QR payload is the public short URL (``/wa/{code}``) rather
than the direct ``wa.me/...`` deeplink so we still log scans via
the tracker. The redirect adds ``?src=qr`` so the click recorder
knows to bump the ``scan_count`` column instead of ``click_count``.

Caveat: WhatsApp deeplinks truncate at ~2000 chars but human
operators rarely paste that much. The UI warns when
``prefilled_message`` is longer than 200 chars — that's the
practical limit beyond which preview previews get clipped on
WhatsApp's own QR-scan UI.
"""

from __future__ import annotations

import io
import logging
from typing import Literal

logger = logging.getLogger(__name__)


QrFormat = Literal["png", "svg"]


_SIZE_MAP: dict[int, int] = {
    256: 6,
    512: 10,
    1024: 20,
}


def _box_size_for(pixels: int) -> int:
    """Map a requested pixel size to qrcode's ``box_size`` arg.

    Falls back to the nearest known mapping; never raises so the
    endpoint can ship a reasonable image even if the caller sends
    an unusual size."""
    return _SIZE_MAP.get(pixels, _SIZE_MAP[512])


def render_png(payload: str, *, size_px: int = 512) -> bytes:
    """Render ``payload`` as a PNG of approximately ``size_px``
    pixels square. Raises :class:`RuntimeError` when qrcode /
    Pillow isn't importable — the router translates to 503."""
    try:
        import qrcode  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover — handled by callers
        raise RuntimeError("qrcode is required for PNG export but is not installed") from exc
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=_box_size_for(size_px),
        border=2,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_svg(payload: str, *, size_px: int = 512) -> bytes:
    """Render ``payload`` as an SVG byte-string. Pure-Python (no
    Pillow needed) — useful for print PDFs and scaling without
    rasterisation artifacts."""
    try:
        import qrcode  # type: ignore[import-untyped]
        from qrcode.image.svg import SvgImage  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover — handled by callers
        raise RuntimeError("qrcode is required for SVG export but is not installed") from exc
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=_box_size_for(size_px),
        border=2,
        image_factory=SvgImage,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image()
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue()


__all__ = ["QrFormat", "render_png", "render_svg"]
