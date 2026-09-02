"""Business logic for the Mailgun inbound webhook.

Three entry points used by the router:

  * :func:`verify_signature` — Mailgun HMAC-SHA256 on
    ``(timestamp + token)`` with ``MAILGUN_SIGNING_KEY``; constant-
    time compare; 5-min timestamp window; optional fallback to
    ``MAILGUN_SIGNING_KEY_PREVIOUS`` for zero-loss key rotation.
  * :func:`persist_pending_inbound` — write the raw multipart form
    (payload + attachments) under
    ``./storage/pending-inbound/<uuid>/`` so the webhook can return
    200 *before* the broker enqueue, and the sweeper (see
    :mod:`pending_inbound_sweeper`) can re-enqueue after a broker
    outage.
  * :func:`enqueue_process_task` — .delay() the Celery ingest task
    (Step 4 fills the body). Fails soft — a broker outage still
    returns 200 to Mailgun; the sweeper picks up later.

The Celery task's substantive ingest (token resolve, SPF/DKIM
check, contact match, threading, workflow event publish) lives in
Step 4's :mod:`.tasks` module; Step 3 ships only the transport.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

try:
    import magic  # python-magic (already in requirements.txt)
except Exception:  # pragma: no cover — dev container missing libmagic
    magic = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# 5-min timestamp skew window. Matches Stripe / Meta industry default.
# Widen to 600s ONLY if false-positives are seen on clock-drift; do
# NOT push past 10min or the replay-cache TTL becomes meaningless.
_TIMESTAMP_SKEW_SECONDS = 300

# Storage root for on-disk pending-inbound directories. Kept *outside*
# the per-org path so the webhook can write BEFORE the token is
# resolved (no org_id yet).
_STORAGE_ROOT_ENV = "STORAGE_ROOT"
_DEFAULT_STORAGE_ROOT = "./storage"
_PENDING_SUBDIR = "pending-inbound"

# Only ASCII letters, digits, dot, dash, underscore are kept in
# attachment filenames on their way to disk. Anything else — including
# path separators, control chars, unicode homoglyphs — is collapsed
# to ``_``. Guards path traversal + filesystem-illegal chars in one
# pass.
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")


def _storage_root() -> Path:
    return Path(os.getenv(_STORAGE_ROOT_ENV, _DEFAULT_STORAGE_ROOT))


def _sanitize_attachment_filename(name: str | None) -> str:
    """Strip path separators + illegal chars from a Mailgun-supplied
    attachment filename. Never returns an empty string."""
    base = os.path.basename((name or "").strip()) or "attachment.bin"
    cleaned = _SAFE_NAME_RE.sub("_", base)[:255]
    return cleaned or "attachment.bin"


def verify_signature(*, timestamp: str, token: str, signature: str) -> bool:
    """Return True iff Mailgun's HMAC verifies against the current
    signing key (or the previous key during a rotation window).

    Formula spelled out here so no implementer picks the wrong one:

        hmac_sha256(
            key   = MAILGUN_SIGNING_KEY,
            input = (timestamp + token).encode("utf-8"),
        ).hexdigest() == signature

    Fails **closed** on:
      * missing / non-integer ``timestamp``
      * ``abs(now - timestamp) > 300s`` (replay window)
      * ``MAILGUN_SIGNING_KEY`` unset in the environment
      * any HMAC input parsing error

    Constant-time compare via :func:`hmac.compare_digest`.
    """
    if not (timestamp and token and signature):
        return False
    try:
        ts_int = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(int(time.time()) - ts_int) > _TIMESTAMP_SKEW_SECONDS:
        return False

    current_key = os.getenv("MAILGUN_SIGNING_KEY", "").strip()
    previous_key = os.getenv("MAILGUN_SIGNING_KEY_PREVIOUS", "").strip()
    if not current_key:
        logger.error(
            "mailgun.verify_signature: MAILGUN_SIGNING_KEY unset — "
            "rejecting all deliveries (fail-closed)"
        )
        return False

    signed = (timestamp + token).encode("utf-8")
    for key in (current_key, previous_key):
        if not key:
            continue
        try:
            expected = hmac.new(
                key.encode("utf-8"), signed, hashlib.sha256
            ).hexdigest()
        except Exception:  # pragma: no cover — defensive
            continue
        if hmac.compare_digest(expected, signature):
            return True
    return False


async def persist_pending_inbound(form: Any) -> Path:
    """Write the raw Mailgun multipart form to disk.

    The webhook path calls this BEFORE the Celery enqueue so a broker
    outage after our 200 doesn't lose the delivery — the sweeper
    (:mod:`.pending_inbound_sweeper`) picks up any directory older
    than 5 minutes and re-enqueues.

    Layout:

        ./storage/pending-inbound/<uuid>/
            payload.json             ← all non-file form fields
            attachment_<n>_<name>    ← each multipart file part

    Returns the absolute directory path (also used as the enqueue arg).
    """
    request_id = uuid.uuid4()
    pending_dir = _storage_root() / _PENDING_SUBDIR / str(request_id)
    pending_dir.mkdir(parents=True, exist_ok=True)

    metadata: dict[str, Any] = {}
    attachment_index = 0

    for key, value in form.multi_items():
        # Starlette's UploadFile has a ``.filename`` attribute; string
        # form fields don't. Discriminate purely on that shape so no
        # extra Starlette import is needed at import time.
        filename = getattr(value, "filename", None)
        if filename:
            safe_name = _sanitize_attachment_filename(filename)
            dst = pending_dir / f"attachment_{attachment_index}_{safe_name}"
            # UploadFile exposes an async ``.read()`` API.
            data = await value.read()
            with open(dst, "wb") as fh:
                fh.write(data)
            # Also record the sanitised name in the metadata so the
            # Step 4 ingest doesn't have to re-parse the filename off
            # the on-disk file name (which now carries our own prefix).
            metadata.setdefault("_attachments", []).append(
                {"index": attachment_index, "filename": safe_name}
            )
            attachment_index += 1
        else:
            # Repeated string keys collapse into a list — Mailgun does
            # this for ``recipient`` when a delivery had multiple
            # ``To``/``Cc`` addresses. Preserve the list shape.
            if key in metadata:
                existing = metadata[key]
                if isinstance(existing, list):
                    existing.append(value)
                else:
                    metadata[key] = [existing, value]
            else:
                metadata[key] = value

    (pending_dir / "payload.json").write_text(
        json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
    )
    return pending_dir


def enqueue_process_task(pending_path: Path) -> bool:
    """Dispatch the ingest Celery task. Return True on success, False
    if the broker refused (which the caller silently swallows — the
    sweeper picks up the directory later).

    Lazy import so a missing celery / broker doesn't crash module
    load. Matches ``core/integrations/meta/webhook.py:HAS_CELERY``.
    """
    try:
        from src.app.core.email.mailgun.tasks import process_mailgun_inbound

        process_mailgun_inbound.delay(str(pending_path))
        return True
    except Exception as exc:  # pragma: no cover — broker outage path
        logger.warning(
            "mailgun.enqueue_process_task failed for %s: %s — "
            "sweeper will pick up",
            pending_path,
            exc,
        )
        return False


# ---------------------------------------------------------------------------
# Payload parsers used by the Step 4 ingest task
# ---------------------------------------------------------------------------


# RFC-3834 says ``Auto-Submitted: no`` means "definitely not
# auto-generated"; any other value counts as auto-generated.
# ``Precedence: bulk|junk|list`` and Microsoft's
# ``X-Auto-Response-Suppress`` cover the older-mail-server side.
_AUTO_RESPONDER_PRECEDENCE = frozenset({"bulk", "junk", "list"})
_AUTO_RESPONSE_SUPPRESS = frozenset({"all", "oof", "autoreply"})

# Mailgun forwards the receiving mailbox's ``Authentication-Results``
# verdict verbatim in ``X-Mailgun-Spf`` (single word: pass|fail|
# softfail|neutral|none) and its DKIM check in ``X-Mailgun-Dkim-
# Signature`` (single word: pass|fail|none).
_SPF_VALUES = frozenset({"pass", "fail", "softfail", "neutral", "none"})
_DKIM_VALUES = frozenset({"pass", "fail", "none"})


def _lc(value: object) -> str:
    """Lowercase-strip helper for header inspection."""
    return str(value or "").strip().lower()


def extract_headers(payload: dict[str, Any]) -> dict[str, str]:
    """Mailgun ships every RFC header individually — most under their
    literal name (``Subject``, ``From``, ``To``, ``Auto-Submitted``,
    …) plus a JSON-encoded ``message-headers`` string for anything
    else. Merge both surfaces into a single case-normalised dict the
    shared ``_persist_inbound_email`` helper can consume.
    """
    merged: dict[str, str] = {}

    # message-headers is a JSON-encoded list of [name, value] pairs.
    raw = payload.get("message-headers")
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, list):
            for entry in parsed:
                if isinstance(entry, list) and len(entry) == 2:
                    name, value = entry
                    if isinstance(name, str):
                        merged[name.strip().lower()] = str(value or "")

    # Then overlay the individually-forwarded headers (Mailgun's
    # canonical spelling — Subject, From, To, Message-Id). These
    # override the message-headers parse because Mailgun sometimes
    # normalises them (e.g. re-encoded subject).
    for header_name in (
        "Subject",
        "From",
        "To",
        "Cc",
        "Message-Id",
        "In-Reply-To",
        "References",
        "Auto-Submitted",
        "Precedence",
        "X-Auto-Response-Suppress",
        "Return-Path",
    ):
        value = payload.get(header_name)
        if value is not None:
            merged[header_name.strip().lower()] = str(value)

    return merged


def parse_spf_result(payload: dict[str, Any]) -> str | None:
    """Return one of ``pass | fail | softfail | neutral | none``, or
    None if Mailgun didn't include the verdict."""
    value = _lc(payload.get("X-Mailgun-Spf") or payload.get("x-mailgun-spf"))
    return value if value in _SPF_VALUES else None


def parse_dkim_result(payload: dict[str, Any]) -> str | None:
    """Return one of ``pass | fail | none``, or None when absent.

    Mailgun's DKIM verdict is ``X-Mailgun-Dkim-Signature: pass|fail``.
    Older deliveries may omit the header — treat as ``None`` (unknown,
    not fail) so we don't drop legitimate mail on incomplete metadata.
    """
    value = _lc(
        payload.get("X-Mailgun-Dkim-Signature")
        or payload.get("x-mailgun-dkim-signature")
    )
    return value if value in _DKIM_VALUES else None


def detect_auto_responder(headers: dict[str, str]) -> bool:
    """Return True if the message looks auto-generated (vacation
    reply, mailing-list, bounce, out-of-office). Callers pass
    ``publish_workflow_events=False`` in that case so a customer's
    OOO reply doesn't fire the ``email.replied`` follow-up automation
    → auto-send → OOO reply loop."""
    auto_submitted = _lc(headers.get("auto-submitted"))
    if auto_submitted and auto_submitted != "no":
        return True
    if _lc(headers.get("precedence")) in _AUTO_RESPONDER_PRECEDENCE:
        return True
    if _lc(headers.get("x-auto-response-suppress")) in _AUTO_RESPONSE_SUPPRESS:
        return True
    return False


def extract_recipient_token(recipient: str) -> str | None:
    """Pull the opaque token out of ``in_<token>@<domain>``. Returns
    None if the recipient shape doesn't match — the ingest task then
    audits ``mailgun.inbound.unknown_recipient`` + drops."""
    if not recipient:
        return None
    local_part = recipient.split("@", 1)[0]
    if not local_part.startswith("in_"):
        return None
    token = local_part[len("in_"):]
    if not token:
        return None
    return token


def extract_all_our_recipients(payload: dict[str, Any]) -> list[str]:
    """Return every recipient in the delivery that resolves to one of
    our ``in_<token>@…`` addresses. Used by the ingest task's
    multi-recipient guard — deliveries with >1 of our tokens are
    ambiguous and get rejected + audited (rare in practice)."""
    hits: list[str] = []
    # ``recipient`` is Mailgun's canonical field; it collapses to a
    # list when the delivery had multiple To/Cc addresses. Handle both.
    raw = payload.get("recipient")
    values: list[str] = []
    if isinstance(raw, str):
        values.append(raw)
    elif isinstance(raw, list):
        values.extend(str(v) for v in raw)
    for v in values:
        for candidate in v.split(","):
            if extract_recipient_token(candidate.strip()) is not None:
                hits.append(candidate.strip())
    return hits


# ---------------------------------------------------------------------------
# Attachment handling (Step 5)
# ---------------------------------------------------------------------------

# Explicit allowlist — ``text/*`` glob deliberately NOT used because it
# includes ``text/html`` which renders inline as an XSS vector when
# operators preview the attachment. If a legit MIME needs adding, list
# it here — never widen to a glob.
_ALLOWED_MIME_TYPES = frozenset(
    {
        "text/plain",
        "text/csv",
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/zip",
    }
)

_PER_FILE_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_PER_MESSAGE_MAX_BYTES = 25 * 1024 * 1024  # 25 MB


def _sniff_mime(path: Path, fallback: str) -> str:
    """libmagic-based content-type sniff. Falls back to the caller's
    declared type only when python-magic isn't installed (dev shim
    guard). The declared type is NEVER trusted for the allowlist
    check — an attacker labelling ``.exe`` as ``image/jpeg`` would
    slip through otherwise."""
    if magic is None:  # pragma: no cover — libmagic optional in some containers
        return fallback
    try:
        return magic.from_file(str(path), mime=True) or fallback
    except Exception:  # pragma: no cover — corrupt file / libmagic hiccup
        return fallback


def extract_and_stage_attachments(
    pending_dir: Path,
    *,
    org_id: uuid.UUID,
    request_id: uuid.UUID,
) -> tuple[list[dict[str, Any]], str | None]:
    """Move validated attachments from pending-inbound/ to staging/.

    Two-phase write (Attacker M5 sweeper-race fix): attachments land
    at ``./storage/{org_id}/staging/{request_id}/`` FIRST, and are
    only moved to ``./storage/{org_id}/messages/{message_id}/`` after
    the ``Message`` row commits (via :func:`commit_attachments`).

    Returns ``(attachments_meta, stripped_reason)``:
      * ``attachments_meta`` — list of JSONB dicts to write into
        ``Message.attachments``. Empty list if the delivery had no
        attachments OR every one was stripped.
      * ``stripped_reason`` — ``None`` when every attachment was
        accepted; a short enum-shaped string otherwise:
        ``size_exceeded`` (per-file OR per-message cap breached),
        ``mime_disallowed`` (sniffed type not in the allowlist).
        The caller writes the reason into ``Message.payload`` so
        operators can see why the mail arrived without the file.
    """
    if not pending_dir.exists():
        return [], None

    staging_root = _storage_root() / str(org_id) / "staging" / str(request_id)
    staging_root.mkdir(parents=True, exist_ok=True)

    attachments: list[dict[str, Any]] = []
    total_bytes = 0
    stripped_reason: str | None = None
    seen_names: dict[str, int] = {}

    # Iterate in sorted order so tests are deterministic.
    for raw_path in sorted(pending_dir.glob("attachment_*")):
        try:
            size = raw_path.stat().st_size
        except FileNotFoundError:
            continue
        if size > _PER_FILE_MAX_BYTES:
            stripped_reason = "size_exceeded"
            continue
        if total_bytes + size > _PER_MESSAGE_MAX_BYTES:
            stripped_reason = "size_exceeded"
            continue

        sniffed = _sniff_mime(raw_path, "application/octet-stream")
        if sniffed not in _ALLOWED_MIME_TYPES:
            stripped_reason = "mime_disallowed"
            continue

        # The pending file is named ``attachment_<idx>_<sanitised>``
        # by ``persist_pending_inbound`` — strip the prefix to get the
        # display name, then re-sanitise + disambiguate on collision.
        display_name = raw_path.name.split("_", 2)[-1] or "attachment.bin"
        safe = _sanitize_attachment_filename(display_name)
        base, ext = os.path.splitext(safe)
        seen = seen_names.get(safe, 0) + 1
        seen_names[safe] = seen
        if seen > 1:
            safe = f"{base}-{seen}{ext}"

        dst = staging_root / safe
        try:
            raw_path.rename(dst)
        except OSError:
            # Cross-filesystem move — copy + unlink fallback. Rare.
            import shutil as _shutil

            _shutil.copy2(raw_path, dst)
            raw_path.unlink(missing_ok=True)

        total_bytes += size
        attachments.append(
            {
                "filename": safe,
                "size": size,
                "content_type": sniffed,
                "storage_key": safe,  # relative to messages/{message_id}/
                "storage_backend": "local",
            }
        )

    if not attachments:
        # Clean up empty staging dir so the sweeper doesn't chase it.
        try:
            staging_root.rmdir()
        except OSError:
            pass

    return attachments, stripped_reason


def commit_attachments(
    *,
    org_id: uuid.UUID,
    request_id: uuid.UUID,
    message_id: uuid.UUID,
) -> None:
    """Move ``staging/{request_id}/`` → ``messages/{message_id}/``.

    Only called AFTER the ``Message`` row commits so a failed insert
    doesn't leave orphaned files under the messages/ tree — the
    orphan sweeper is designed to only touch messages/ dirs with no
    matching row, and running twice-a-day is fine for that path;
    staging/ dirs get swept aggressively (>1h age).
    """
    staging = _storage_root() / str(org_id) / "staging" / str(request_id)
    if not staging.exists():
        return
    final = _storage_root() / str(org_id) / "messages" / str(message_id)
    final.mkdir(parents=True, exist_ok=True)
    for entry in staging.iterdir():
        target = final / entry.name
        try:
            entry.rename(target)
        except OSError:
            import shutil as _shutil

            _shutil.copy2(entry, target)
            entry.unlink(missing_ok=True)
    try:
        staging.rmdir()
    except OSError:
        pass


def parse_sender_email(payload: dict[str, Any]) -> str:
    """Return the lowercase envelope sender (``sender`` field, falling
    back to ``From`` header). Used for contact matching."""
    raw = str(
        payload.get("sender") or payload.get("From") or payload.get("from") or ""
    ).strip()
    if "<" in raw and ">" in raw:
        # ``"Alice" <alice@ex.com>`` shape from the From header.
        raw = raw[raw.index("<") + 1 : raw.index(">")]
    return raw.lower()


__all__ = [
    "commit_attachments",
    "detect_auto_responder",
    "enqueue_process_task",
    "extract_all_our_recipients",
    "extract_and_stage_attachments",
    "extract_headers",
    "extract_recipient_token",
    "parse_dkim_result",
    "parse_sender_email",
    "parse_spf_result",
    "persist_pending_inbound",
    "verify_signature",
]
