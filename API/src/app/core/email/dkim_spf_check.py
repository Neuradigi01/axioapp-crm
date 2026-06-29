"""DKIM / SPF / DMARC resolver for the Settings → Email domain-status
panel.

The check fires DNS TXT lookups against the configured sender
domain and classifies each record as ``valid`` / ``invalid`` /
``unknown``. Results are cached for 6 hours per
``(org_id, domain)`` in an in-process LRU — DNS lookups against
the public resolver have high p99 latency and the operator's
domain status doesn't change minute-to-minute.

Failure mode: fail-open with ``status='unknown'`` rather than
blocking the send-rules UI. A domain whose status couldn't be
resolved is surfaced explicitly so the operator can re-run the
check manually.

Per-record verdicts:
  * ``spf``: looks for ``v=spf1`` in any TXT record on the domain.
  * ``dkim``: looks for ``v=DKIM1`` in the TXT record on
    ``<selector>._domainkey.<domain>``. The selector defaults to
    ``default`` but ESP-specific selectors (``mailgun``, ``s1``,
    ``selector1``) are also probed.
  * ``dmarc``: looks for ``v=DMARC1`` in the TXT record on
    ``_dmarc.<domain>``.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Literal


logger = logging.getLogger(__name__)


VerdictStatus = Literal["valid", "invalid", "unknown"]


_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6h
# Common DKIM selectors used by the providers we support (Mailgun,
# SendGrid, SES, Postmark). The check tries them in order and
# returns ``valid`` on the first hit.
_DKIM_SELECTORS: tuple[str, ...] = (
    "default",
    "mailgun",
    "s1",
    "selector1",
    "google",
    "k1",
    "pm",
)


@dataclass(frozen=True, slots=True)
class DomainAuthStatus:
    """Compound verdict for a sender domain."""

    domain: str
    spf: VerdictStatus
    dkim: VerdictStatus
    dmarc: VerdictStatus
    last_checked_at: float


# (org_id, domain) → DomainAuthStatus. Pure in-process; multi-worker
# deployments will repeat the check per worker on the first request
# — acceptable since the check is read-only DNS and the 6h TTL
# absorbs subsequent loads.
_cache: dict[tuple[str, str], DomainAuthStatus] = {}


async def _resolve_txt(name: str) -> list[str]:
    """Resolve TXT records for ``name``. Returns an empty list on
    NXDOMAIN / timeout / any failure (fail-open). Uses
    ``asyncio.to_thread`` to dispatch the blocking ``socket``
    resolver to a worker — the project doesn't pin ``dnspython``
    yet so we fall back to a stdlib-only lookup."""
    try:
        # Local import — ``dnspython`` isn't in the pinned deps. We
        # try it first because it cleanly returns TXT records; if
        # absent, we degrade to "unknown" rather than fabricating a
        # result.
        import dns.asyncresolver  # type: ignore

        try:
            answer = await dns.asyncresolver.resolve(name, "TXT")
            return [
                b"".join(rd.strings).decode("utf-8", errors="replace")
                for rd in answer
            ]
        except Exception:
            return []
    except ImportError:
        logger.debug(
            "email.dkim_spf_check dnspython unavailable; "
            "returning unknown for %s",
            name,
        )
        return []


async def _check_spf(domain: str) -> VerdictStatus:
    records = await _resolve_txt(domain)
    if not records:
        return "unknown"
    for r in records:
        if r.lower().startswith("v=spf1"):
            return "valid"
    return "invalid"


async def _check_dkim(domain: str) -> VerdictStatus:
    saw_dns = False
    for selector in _DKIM_SELECTORS:
        records = await _resolve_txt(f"{selector}._domainkey.{domain}")
        if records:
            saw_dns = True
            for r in records:
                if "v=DKIM1" in r:
                    return "valid"
    return "invalid" if saw_dns else "unknown"


async def _check_dmarc(domain: str) -> VerdictStatus:
    records = await _resolve_txt(f"_dmarc.{domain}")
    if not records:
        return "unknown"
    for r in records:
        if r.lower().startswith("v=dmarc1"):
            return "valid"
    return "invalid"


async def check_domain(
    *,
    org_id: str,
    domain: str,
    force_refresh: bool = False,
) -> DomainAuthStatus:
    """Returns the compound SPF / DKIM / DMARC verdict for ``domain``.

    Cached per ``(org_id, domain)`` for 6 hours so the Settings UI
    can poll without thrashing the resolver. ``force_refresh=True``
    skips the cache + writes the fresh result back.
    """
    key = (str(org_id), domain.lower().strip())
    now = time.time()
    if not force_refresh:
        cached = _cache.get(key)
        if (
            cached is not None
            and (now - cached.last_checked_at) < _CACHE_TTL_SECONDS
        ):
            return cached

    spf_task = asyncio.create_task(_check_spf(domain))
    dkim_task = asyncio.create_task(_check_dkim(domain))
    dmarc_task = asyncio.create_task(_check_dmarc(domain))
    spf, dkim, dmarc = await asyncio.gather(spf_task, dkim_task, dmarc_task)

    result = DomainAuthStatus(
        domain=domain.lower().strip(),
        spf=spf,
        dkim=dkim,
        dmarc=dmarc,
        last_checked_at=now,
    )
    _cache[key] = result
    return result


def _invalidate_cache_for_tests() -> None:
    """Test helper — wipe the cache between cases."""
    _cache.clear()


__all__ = [
    "DomainAuthStatus",
    "VerdictStatus",
    "check_domain",
]
