"""Service layer for the public widget submission endpoint.

`submit()` is the single entry point — the router does nothing but
extract HTTP details (key from header, IP from request) and call this.

Pipeline:

  1. Key required (header or body field). Missing → 401.
  2. Key lookup via `embed.service.find_by_plain_key`. Missing /
     revoked / garbage → 401 with a generic message (don't leak
     which keys exist).
  3. Per-key + per-IP rate limit (sliding window, in-memory). Either
     overage → 429 with `Retry-After` set to the longer of the two.
  4. Load the org's widget config (or bundle defaults).
  5. Honeypot check — non-empty → silent 200 + audit. Bots learn
     nothing about being detected.
  6. Min-fill-time check — submissions arriving < `min_fill_time_ms`
     after the form was rendered, or with `rendered_at` in the future
     / > 24h in the past, → silent 200 + audit. Bots fill the form in
     ms; legit humans take seconds.
  7. reCAPTCHA check (if enabled in the org's config) — missing or
     low-score token → silent 200 + audit. Google's siteverify is the
     verdict; we fail closed on network / parse failures.
  8. Open a tenant context for the key's org (since the public endpoint
     has no JWT, this is what authorises the dedup query + lead/contact
     writes against RLS).
  9. Dedup-by-phone-or-email. If existing contact found, reuse its id.
     Otherwise create a new contact.
  10. Create a lead with `source='widget'`, `actor_user_id=None`,
      and the `attribution` payload from the request.
  11. Emit `embed.submission.accepted` audit event.

`actor_user_id=None` is correct: there's no logged-in CRM user driving
this — it's an anonymous form submission from a customer's website.
Audit rows for these submissions correctly show `user_id=NULL`.

**Why spam gates run AFTER key lookup:** earlier versions short-
circuited on the honeypot before key resolution to save a DB hit.
That made the audit event useless (no org_id) and meant the per-org
`min_fill_time_ms` config couldn't be applied. Reordering costs one
indexed lookup per bot submission — cheap relative to the value of
per-org tuning + proper audit visibility.
"""
from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status

from src.app.core import audit
from src.app.core.contacts.schemas import ContactCreate
from src.app.core.contacts.service import create_contact
from src.app.core.embed import log_service
from src.app.core.embed.config_service import public_get as public_get_config
from src.app.core.embed.models import EmbedSubmissionOutcome
from src.app.core.embed.rate_limit import check_per_ip, check_per_key
from src.app.core.embed.recaptcha import verify_token as verify_recaptcha_token
from src.app.core.embed.schemas import (
    EmbedSubmission,
    WidgetConfigDocument,
    WidgetConfigField,
    WidgetConfigSpamProtection,
)
from src.app.core.embed.service import find_by_plain_key
from src.app.core.leads.imports.dedup import find_existing_contact
from src.app.core.leads.models import LeadSource
from src.app.core.leads.schemas import LeadCreate
from src.app.core.leads.service import create_lead
from src.app.shared.context import RequestContext, reset_context, set_context
from src.app.shared.db import async_session


logger = logging.getLogger(__name__)


# Clock-skew tolerance for `rendered_at`. Submissions claiming to have
# been rendered more than this far in the past are treated as suspect
# (replay attacks, very stale tabs). 24h covers legit users who left
# the form open overnight without crossing into "this is a stored
# token being replayed weeks later" territory.
_RENDERED_AT_MAX_AGE = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    """What the router converts to a `EmbedSubmissionResponse`."""

    accepted: bool                       # True = lead created
    lead_id: Optional[uuid.UUID]         # None for silent-drop / honeypot
    thank_you_url: Optional[str]         # Step 3's widget config will populate


async def submit(
    *,
    payload: EmbedSubmission,
    header_key: Optional[str],
    ip: str,
) -> SubmissionResult:
    """Process one widget submission. Raises HTTPException on auth /
    rate-limit failures; returns SubmissionResult otherwise.

    A silent-drop (honeypot triggered, min-time gate failed, reCAPTCHA
    rejected) returns a result with `accepted=False, lead_id=None` and
    the caller responds with a 200 — bots don't learn they were caught.
    """
    # 1. Resolve the embed key. Header wins over body.
    plain_key = header_key or payload.embed_key
    if not plain_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing embed key.",
        )

    # 2. Key lookup. find_by_plain_key opens its own session and
    # bypasses tenant-context (no context set yet on this request).
    key_row = await find_by_plain_key(plain_key, ip=ip)
    if key_row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked embed key.",
        )

    # 3. Rate limit per-key + per-IP. Either trip → 429 (also logged
    # so Owners see "we're being hammered" in the submission log).
    rl_key = check_per_key(key_row.prefix)
    rl_ip = check_per_ip(ip)
    if not rl_key.allowed or not rl_ip.allowed:
        retry_after = max(rl_key.retry_after, rl_ip.retry_after)
        await log_service.record(
            org_id=key_row.org_id,
            key_id=key_row.id,
            outcome=EmbedSubmissionOutcome.rate_limited,
            reason="per_key" if not rl_key.allowed else "per_ip",
            ip=ip,
            referrer=payload.attribution.referrer,
            landing_url=payload.attribution.landing_url,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please slow down.",
            headers={"Retry-After": str(math.ceil(retry_after))},
        )

    org_id = key_row.org_id
    key_id = key_row.id

    # 4. Load the org's widget config (or bundle defaults).
    config_row = await public_get_config(org_id)
    if config_row is not None:
        document = WidgetConfigDocument.model_validate(config_row.config)
    else:
        from src.app.core.embed.config_service import _default_document

        document = _default_document()
    spam = document.spam_protection

    # 5. Honeypot check. Audit context is the key's org so the Owner
    # can see spam blocks in Step 9's submission log.
    if payload.honeypot:
        await _record_spam_reject(
            payload=payload,
            org_id=org_id,
            key_id=key_id,
            reason="honeypot",
            ip=ip,
        )
        return SubmissionResult(
            accepted=False, lead_id=None, thank_you_url=None
        )

    # 6. Min-fill-time check. Skip entirely when the org has set
    # `min_fill_time_ms=0` (escape hatch for low-traffic test orgs).
    if spam.min_fill_time_ms > 0:
        if not _passes_min_fill_time(
            rendered_at=payload.rendered_at,
            min_fill_time_ms=spam.min_fill_time_ms,
        ):
            await _record_spam_reject(
                payload=payload,
                org_id=org_id,
                key_id=key_id,
                reason="min_time",
                ip=ip,
            )
            return SubmissionResult(
                accepted=False, lead_id=None, thank_you_url=None
            )

    # 7. reCAPTCHA check (only when the org has enabled it).
    if spam.recaptcha_enabled:
        ok = await _check_recaptcha(
            payload=payload,
            spam=spam,
            org_id=org_id,
            key_id=key_id,
            ip=ip,
        )
        if not ok:
            return SubmissionResult(
                accepted=False, lead_id=None, thank_you_url=None
            )

    # 8. Validate payload against the org's widget config.
    try:
        _validate_payload_against_config(payload, document)
    except HTTPException as exc:
        # Surface the validation error to the caller, but log it as an
        # `invalid_payload` row so the Owner sees a pattern (stale
        # cached config, forged submissions) in the submission log.
        await log_service.record(
            org_id=org_id,
            key_id=key_id,
            outcome=EmbedSubmissionOutcome.invalid_payload,
            reason=_truncate_reason(exc.detail),
            ip=ip,
            referrer=payload.attribution.referrer,
            landing_url=payload.attribution.landing_url,
        )
        raise

    # 9. Set tenant context so RLS + audit `org_id` derive correctly.
    ctx_token = set_context(RequestContext(org_id=org_id, user_id=None))
    try:
        async with async_session() as session:
            # 9a. Dedup-by-phone-or-email — reuse the same helper the
            # bulk-import processor uses. If the visitor already exists
            # as a contact, we don't create a second contact row; we
            # do create a new lead so the rep sees a fresh inquiry.
            existing_id = await find_existing_contact(
                session,
                org_id=org_id,
                phone=payload.phone,
                email=payload.email,
            )
            if existing_id is not None:
                contact_id = existing_id
            else:
                # Combine interest + notes into the contact's notes
                # field so we don't lose the data Step 3's widget
                # config hasn't decided where to land yet.
                combined_notes = _combine_notes(
                    payload.interest, payload.notes
                )
                # Split custom_data into contact vs lead buckets based
                # on each field's `entity` in the org's widget config.
                # Empties dropped so they don't land as "" in JSONB.
                contact_custom_data, lead_custom_data = (
                    _split_custom_data(payload.custom_data or {}, document)
                )
                contact = await create_contact(
                    session,
                    org_id=org_id,
                    payload=ContactCreate(
                        full_name=payload.full_name,
                        phone=payload.phone,
                        email=payload.email,
                        source="widget",
                        notes=combined_notes,
                        custom_data=contact_custom_data,
                    ),
                    # Visitors filling out a public widget form can't
                    # possibly know the org's required custom fields
                    # that AREN'T opted in to the widget. Required
                    # fields that ARE on the widget are already enforced
                    # by `_validate_payload_against_config` above; staff
                    # fill the rest in via the edit form afterwards.
                    require_all_required=False,
                )
                contact_id = contact.id

            # 10. Create the lead. Same reasoning as create_contact —
            # widget visitors don't know the org's required custom
            # fields on the lead either. Lead-entity custom-data values
            # (e.g. `companyname`) flow in via `lead_custom_data`.
            lead = await create_lead(
                session,
                org_id=org_id,
                payload=LeadCreate(
                    contact_id=contact_id,
                    source=LeadSource.widget,
                    attribution=payload.attribution.model_dump(
                        exclude_none=False
                    ),
                    custom_data=lead_custom_data,
                ),
                require_all_required=False,
            )

        # 11. Audit. The org context is still set so audit.log derives
        # org_id from it; user_id stays None (anonymous submission).
        await audit.log(
            "embed.submission.accepted",
            entity_type="lead",
            entity_id=lead.id,
            after={
                "lead_id": str(lead.id),
                "contact_id": str(contact_id),
                "key_id": str(key_id),
                "key_prefix": key_row.prefix,
                "referrer": payload.attribution.referrer,
            },
        )
        # 12. Submission log row — drives the Settings → Submission
        # log sub-tab. log_service.record opens its own session +
        # context so it works regardless of the parent's state.
        await log_service.record(
            org_id=org_id,
            key_id=key_id,
            outcome=EmbedSubmissionOutcome.accepted,
            ip=ip,
            referrer=payload.attribution.referrer,
            landing_url=payload.attribution.landing_url,
            lead_id=lead.id,
        )
        return SubmissionResult(
            accepted=True, lead_id=lead.id, thank_you_url=None
        )
    finally:
        reset_context(ctx_token)


def _passes_min_fill_time(
    *,
    rendered_at: Optional[datetime],
    min_fill_time_ms: int,
) -> bool:
    """True iff the submission was rendered at least `min_fill_time_ms`
    ago, with a `rendered_at` value that's neither in the future nor
    > 24h in the past.

    Strict on `rendered_at=None` — bots could trivially bypass the gate
    by omitting the field, so a missing value when the gate is enabled
    counts as a failure. The widget renderer always sends it.
    """
    if rendered_at is None:
        return False
    now = datetime.now(timezone.utc)
    rendered = (
        rendered_at
        if rendered_at.tzinfo is not None
        else rendered_at.replace(tzinfo=timezone.utc)
    )
    delta = now - rendered
    if delta < timedelta(0):
        # Future timestamps — clock-skewed bot or forged payload.
        return False
    if delta > _RENDERED_AT_MAX_AGE:
        # Stale beyond plausible legit use (tab open > 24h).
        return False
    return delta >= timedelta(milliseconds=min_fill_time_ms)


async def _check_recaptcha(
    *,
    payload: EmbedSubmission,
    spam: WidgetConfigSpamProtection,
    org_id: uuid.UUID,
    key_id: uuid.UUID,
    ip: str,
) -> bool:
    """Run the reCAPTCHA gate. Emits the appropriate `rejected_spam`
    audit event on failure (token missing → `recaptcha_invalid`,
    Google says no → `recaptcha_low_score`). Returns True on success."""
    token = payload.recaptcha_token
    if not token:
        await _record_spam_reject(
            payload=payload,
            org_id=org_id,
            key_id=key_id,
            reason="recaptcha_invalid",
            ip=ip,
        )
        return False

    # spam.recaptcha_secret_key is guaranteed by the schema's
    # model_validator when recaptcha_enabled=True. The assert below
    # is for the type-checker / defence-in-depth — if it fires, the
    # config validator was bypassed somehow.
    assert spam.recaptcha_secret_key is not None
    verified = await verify_recaptcha_token(
        token=token,
        secret=spam.recaptcha_secret_key,
        remote_ip=ip if ip and ip != "unknown" else None,
    )
    if not verified:
        await _record_spam_reject(
            payload=payload,
            org_id=org_id,
            key_id=key_id,
            reason="recaptcha_low_score",
            ip=ip,
        )
        return False
    return True


async def _record_spam_reject(
    *,
    payload: EmbedSubmission,
    org_id: uuid.UUID,
    key_id: uuid.UUID,
    reason: str,
    ip: str,
) -> None:
    """One-stop spam-reject helper. Fires both the audit event
    (`embed.submission.rejected_spam`) AND the submission-log row
    (`outcome=rejected_spam`) so Settings → Submission log shows
    every blocked attempt next to the accepted ones.

    Org context is supplied explicitly via the `org_id=` keyword
    because the request context isn't set yet at the spam-gate
    point in the pipeline (we deliberately reject BEFORE opening
    the tenant scope to keep the write side untouched for bot
    traffic).
    """
    logger.info(
        "embed.submission.rejected_spam reason=%s key=%s ip=%s",
        reason,
        key_id,
        ip,
    )
    await audit.log(
        "embed.submission.rejected_spam",
        entity_type="embed_key",
        entity_id=key_id,
        org_id=org_id,
        ip=ip,
        after={
            "key_id": str(key_id),
            "reason": reason,
            "ip_hash": log_service.hash_ip(ip),
        },
    )
    await log_service.record(
        org_id=org_id,
        key_id=key_id,
        outcome=EmbedSubmissionOutcome.rejected_spam,
        reason=reason,
        ip=ip,
        referrer=payload.attribution.referrer,
        landing_url=payload.attribution.landing_url,
    )


def _truncate_reason(value: object, length: int = 500) -> str:
    """Coerce an HTTPException `detail` (str / list / dict) into a
    short string for the submission log's `reason` column."""
    text = value if isinstance(value, str) else str(value)
    return text[:length]


def _split_custom_data(
    submitted: dict[str, object],
    document: WidgetConfigDocument,
) -> tuple[dict[str, object], dict[str, object]]:
    """Split the visitor's flat `custom_data` payload into (contact,
    lead) buckets based on each field's `entity` in the widget config.

    Empty / None values are dropped from both buckets so widget
    submissions don't pollute existing JSONB with literal empties.
    Keys not in the config (already 422'd upstream by the validator)
    fall through to the contact bucket as a defensive default — they
    shouldn't reach here.
    """
    entity_by_key: dict[str, str] = {
        f.key: f.entity
        for f in document.fields
        if f.field_source == "custom"
    }
    contact_bucket: dict[str, object] = {}
    lead_bucket: dict[str, object] = {}
    for key, value in submitted.items():
        if value is None or (isinstance(value, str) and value == ""):
            continue
        entity = entity_by_key.get(key, "contact")
        if entity == "lead":
            lead_bucket[key] = value
        else:
            contact_bucket[key] = value
    return contact_bucket, lead_bucket


def _combine_notes(
    interest: Optional[str], notes: Optional[str]
) -> Optional[str]:
    """Fold the widget's `interest` + `notes` into a single notes
    string so neither value is lost in v1. A future improvement
    could route these to dedicated standard / custom fields per
    the org's config.
    """
    pieces: list[str] = []
    if interest:
        pieces.append(f"Interest: {interest}")
    if notes:
        pieces.append(notes)
    return "\n\n".join(pieces) if pieces else None


def _validate_payload_against_config(
    payload: EmbedSubmission, document: WidgetConfigDocument
) -> None:
    """Enforce the org's widget config at submission time.

    Rules (both standard and custom-source fields):
      1. Every payload value (standard or custom) that's present
         must correspond to a field configured for this org. The widget
         only renders configured fields, so submissions for unconfigured
         fields signal either a stale cached config or a forged payload.
      2. Every required field per the config must be non-empty.
      3. Any `select` field's value must be one of the configured
         `options` (applies to `interest` plus any custom select fields).

    Raises HTTPException 422 on any rule violation. `full_name` is
    always allowed regardless of config because Pydantic already
    enforces it at the request-body level.
    """
    standard_fields: dict[str, WidgetConfigField] = {
        f.key: f for f in document.fields if f.field_source == "standard"
    }
    custom_fields: dict[str, WidgetConfigField] = {
        f.key: f for f in document.fields if f.field_source == "custom"
    }

    # Rule 1a: standard-source fields. Pydantic already restricts the
    # payload's top-level keys to the documented EmbedSubmission shape
    # — we only need to gate the OPTIONAL ones (phone / email / interest
    # / notes) against the per-org config. full_name is always required
    # by the schema.
    supplied_standard: dict[str, Optional[str]] = {
        "phone": payload.phone,
        "email": payload.email,
        "interest": payload.interest,
        "notes": payload.notes,
    }
    for key, value in supplied_standard.items():
        if value is None or value == "":
            continue
        if key not in standard_fields:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"Field '{key}' is not configured for this widget. "
                    f"Allowed standard fields: {sorted(standard_fields)}."
                ),
            )

    # Rule 1b: custom-source values must reference a configured custom
    # field. Visitors aren't allowed to write to arbitrary custom keys
    # — that would bypass the Owner's opt-in toggle and could write to
    # internal-only fields like `internal_notes`.
    for key, value in (payload.custom_data or {}).items():
        if value is None or (isinstance(value, str) and value == ""):
            continue
        if key not in custom_fields:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"Custom field '{key}' is not exposed on this widget. "
                    f"Allowed custom fields: {sorted(custom_fields)}."
                ),
            )

    # Rule 2: required fields per config must be present. Pulls values
    # from both standard (top-level) and custom (custom_data) buckets.
    visitor_values: dict[str, Optional[object]] = {
        "full_name": payload.full_name,
        **supplied_standard,
        **{k: v for k, v in (payload.custom_data or {}).items()},
    }
    missing_required: list[str] = []
    for field in document.fields:
        if not field.required:
            continue
        raw = visitor_values.get(field.key)
        if raw is None:
            missing_required.append(field.key)
        elif isinstance(raw, str) and not raw.strip():
            missing_required.append(field.key)
    if missing_required:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Required field(s) missing: {missing_required}."
            ),
        )

    # Rule 3: select-typed fields must use a configured option.
    # Applies to `interest` (the only standard select) plus every
    # custom field of type=select.
    interest_def = standard_fields.get("interest")
    if (
        interest_def is not None
        and interest_def.field_type == "select"
        and interest_def.options
        and payload.interest
        and payload.interest not in interest_def.options
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"interest must be one of {interest_def.options}, "
                f"got {payload.interest!r}."
            ),
        )
    for field in custom_fields.values():
        if field.field_type != "select" or not field.options:
            continue
        value = (payload.custom_data or {}).get(field.key)
        if value and value not in field.options:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"Custom field '{field.key}' must be one of "
                    f"{field.options}, got {value!r}."
                ),
            )


__all__ = ["SubmissionResult", "submit"]
