"""Data-access layer for the contacts module.

Pure query helpers — no transactions, no audit, no commits. Leaf
module; never imports a `service.py`.

Two duplicate-by-shape patterns in the codebase: by id (the canonical
"hydrate this contact" call) and by phone (walk-in reception's
"do we already know this number?" check + conversation routing's
inbound-message-to-contact resolver).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import (
    and_,
    exists,
    func,
    or_,
    select,
    text,
)
from sqlalchemy import (
    delete as sa_delete,
)
from sqlalchemy import (
    update as sa_update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement, Select

from src.app.core.contacts.models import Contact
from src.app.core.leads.models import Lead
from src.app.core.users.models import OrganizationMember, User
from src.app.core.walk_ins.models import WalkIn


async def get_contact(session: AsyncSession, contact_id: uuid.UUID) -> Contact | None:
    """Resolve a contact by its UUID PK.

    Tenant scoping is applied automatically by the `do_orm_execute`
    listener (Contact is `TenantScoped`), so the row is only returned
    when it belongs to the active request's org. Callers that run
    outside a tenant context (Celery, scripts) must set
    `RequestContext.org_id` first.
    """
    result = await session.execute(select(Contact).where(Contact.id == contact_id))
    return result.scalar_one_or_none()


async def get_contact_by_phone(session: AsyncSession, phone: str) -> Contact | None:
    """Resolve a contact by phone number within the active tenant.

    Returns the most-recently-created match. `phone` is NOT unique in
    the tenant (data-entry drift, imports, etc.) — old behaviour used
    `scalar_one_or_none()` which raised `MultipleResultsFound` on
    duplicates, 500ing the reception desk. Now we order + limit(1).

    Anonymised contacts (DPDP right-to-be-forgotten) are excluded so
    walk-in / inbound-message reception cannot re-attach fresh
    activity to a wiped record.
    """
    result = await session.execute(
        select(Contact)
        .where(Contact.phone == phone)
        .where(Contact.anonymised_at.is_(None))
        .order_by(Contact.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def find_contact_by_email(
    session: AsyncSession, *, org_id: uuid.UUID, email: str
) -> Contact | None:
    """Resolve a contact by email within a specific org.

    Case-insensitive lookup on ``Contact.email``. ``org_id`` is passed
    EXPLICITLY (not left to the tenant listener) because the Mailgun
    ingest path runs in a Celery task where the caller has just
    resolved the org from an inbound token — passing it in guarantees
    the query never leaks across tenants regardless of ambient
    context state (Attacker C3 finding from PLANNING_RULES review).

    Returns the most-recently-updated match when the org has multiple
    contacts sharing the email (rare, but the DB permits it — no
    unique constraint on ``(org_id, email)``). Anonymised contacts
    are excluded so an inbound reply doesn't reattach activity to a
    DPDP-wiped record.
    """
    normalized = email.strip().lower()
    result = await session.execute(
        select(Contact)
        .where(Contact.org_id == org_id)
        .where(func.lower(Contact.email) == normalized)
        .where(Contact.anonymised_at.is_(None))
        .order_by(Contact.updated_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def insert_contact(session: AsyncSession, contact: Contact) -> None:
    """Register an already-constructed Contact for INSERT. Caller
    commits or flushes. Used by webhook intake paths that need to
    materialise a placeholder contact for an unknown phone number
    (conversations, walk-ins)."""
    session.add(contact)


async def delete_contact_row(session: AsyncSession, contact: Contact) -> None:
    """Hard-delete one Contact row."""
    await session.delete(contact)


# --- filter helpers -----------------------------------------------------


def _build_filters(
    *,
    q: str | None,
    sources: list[str] | None,
    tags: list[str] | None,
    assigned_to_ids: list[uuid.UUID] | None,
    custom_filters: Iterable[tuple[str, str]],
    exclude_anonymised: bool = False,
    lead_statuses: list[str] | None = None,
    lead_stages: list[str] | None = None,
    lead_sources: list[str] | None = None,
    lead_form_ids: list[uuid.UUID] | None = None,
) -> list[ColumnElement[bool]]:
    """Shared filter assembler used by list / export / count helpers.

    Multi-value semantics — `sources`, `tags`, and `assigned_to_ids`
    take a list and produce an OR-set (rows matching any listed value).
    Empty / None lists are ignored. Backed by the column-header filter
    popover on the frontend, which lets an operator tick several
    values on the same column at once. Same shape any other list page
    can adopt when it wires the shared `app-column-filter`.
    """
    filters: list[ColumnElement[bool]] = []
    if q:
        like = f"%{q}%"
        filters.append(
            or_(
                Contact.full_name.ilike(like),
                Contact.phone.ilike(like),
                Contact.email.ilike(like),
            )
        )
    if sources:
        filters.append(Contact.source.in_(sources))
    if tags:
        # OR of per-tag `@>` (contains) checks — row matches when its
        # tags array contains at least one of the requested tags. Uses
        # the same operator as the existing single-tag filter so no new
        # index characteristic is introduced.
        filters.append(or_(*(Contact.tags.contains([t]) for t in tags)))
    if assigned_to_ids:
        filters.append(Contact.assigned_to_id.in_(assigned_to_ids))
    if exclude_anonymised:
        filters.append(Contact.anonymised_at.is_(None))
    for key, value in custom_filters:
        filters.append(Contact.custom_data[key].astext == value)

    # Lead-linked filters — restrict to contacts that have at least one
    # Lead row matching each requested predicate. Each filter emits an
    # EXISTS subquery so tenant scoping (RLS) still applies on the
    # inner Lead select via the ``do_orm_execute`` listener. Passing
    # multiple lists is AND-across filters, OR-within each list (e.g.
    # ``lead_statuses=[active,won]`` = "has an active OR won lead";
    # combining with ``lead_stages=[negotiation]`` = "has an active OR
    # won lead AND has a lead in negotiation" — semantically two
    # separate leads may satisfy each, mirroring how the leads page's
    # own filter combines).
    if lead_statuses:
        filters.append(
            exists(
                select(Lead.id)
                .where(Lead.contact_id == Contact.id)
                .where(Lead.status.in_(lead_statuses))
            )
        )
    if lead_stages:
        filters.append(
            exists(
                select(Lead.id)
                .where(Lead.contact_id == Contact.id)
                .where(Lead.pipeline_stage.in_(lead_stages))
            )
        )
    if lead_form_ids:
        # Multi-form (Step 4): every widget-sourced lead carries
        # ``attribution.form_id`` — filter to contacts with at least
        # one lead whose form id is in the requested set. Compares
        # the JSONB path as text (uuid is stored as its string form
        # in the widget submission handler). Only lead rows with
        # ``source='widget'`` populate ``form_id`` today, so the
        # extra source predicate short-circuits non-widget rows out
        # of the EXISTS lookup and lets Postgres use the leads
        # (contact_id, source) index.
        form_id_strings = [str(fid) for fid in lead_form_ids]
        filters.append(
            exists(
                select(Lead.id)
                .where(Lead.contact_id == Contact.id)
                .where(Lead.source == "widget")
                .where(Lead.attribution["form_id"].astext.in_(form_id_strings))
            )
        )
    if lead_sources:
        filters.append(
            exists(
                select(Lead.id)
                .where(Lead.contact_id == Contact.id)
                .where(Lead.source.in_(lead_sources))
            )
        )
    return filters


def build_contact_list_query(
    *,
    q: str | None,
    sources: list[str] | None,
    tags: list[str] | None,
    assigned_to_ids: list[uuid.UUID] | None,
    custom_filters: Iterable[tuple[str, str]],
    sort_column: Any,
    sort: str,
    order: str,
    exclude_anonymised: bool = False,
    lead_statuses: list[str] | None = None,
    lead_stages: list[str] | None = None,
    lead_sources: list[str] | None = None,
    lead_form_ids: list[uuid.UUID] | None = None,
) -> Select[tuple[Contact]]:
    """Assemble the paginated list query with filter + sort applied.

    Returned `Select` is fed to `shared.db.pagination.paginate` by the
    caller. `sort_column` is the whitelisted column object the service
    resolves from `_SORT_COLUMNS` (kept there so the alphabet of valid
    keys lives next to the route schema).
    """
    filters = _build_filters(
        q=q,
        sources=sources,
        tags=tags,
        assigned_to_ids=assigned_to_ids,
        custom_filters=custom_filters,
        exclude_anonymised=exclude_anonymised,
        lead_statuses=lead_statuses,
        lead_stages=lead_stages,
        lead_sources=lead_sources,
        lead_form_ids=lead_form_ids,
    )
    base = select(Contact)
    if filters:
        base = base.where(and_(*filters))

    if sort == "last_activity_at":
        # Fold `created_at` into the sort key via COALESCE so a
        # never-touched contact ranks by its creation time — a
        # just-added contact (last_activity_at NULL, created_at =
        # now) lands at the top instead of being pushed to the
        # bottom by NULLS LAST. Contacts with real activity still
        # rank by their most recent touch. ``Contact.id`` stays as
        # a final deterministic tie for absolute stability.
        activity_or_created = func.coalesce(Contact.last_activity_at, Contact.created_at)
        primary = activity_or_created.asc() if order == "asc" else activity_or_created.desc()
        return base.order_by(primary, Contact.id.desc())
    primary = sort_column.asc() if order == "asc" else sort_column.desc()
    return base.order_by(primary, Contact.id.desc())


async def is_user_active_member_of_org(
    session: AsyncSession, *, user_uuid: uuid.UUID, org_id: uuid.UUID
) -> bool:
    """True iff the user has an active membership row in the given org."""
    result = await session.execute(
        select(OrganizationMember.id)
        .join(User, User.id == OrganizationMember.user_member_id)
        .where(
            User.legacy_uuid == user_uuid,
            OrganizationMember.organization_id == org_id,
            OrganizationMember.is_active.is_(True),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def list_contacts_by_ids_in_org(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    org_id: uuid.UUID,
) -> list[Contact]:
    """Batched hydrate for the bulk-reassign path. Empty input → empty
    list without a round-trip. `org_id` is asserted in the WHERE clause
    as a belt to the ORM tenant filter."""
    if not ids:
        return []
    result = await session.execute(
        select(Contact).where(Contact.id.in_(ids), Contact.org_id == org_id)
    )
    return list(result.scalars().all())


async def delete_contacts_in_org(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    org_id: uuid.UUID,
) -> int:
    """Hard-delete contacts by id within one org. Returns rowcount."""
    if not ids:
        return 0
    result = await session.execute(
        sa_delete(Contact).where(Contact.id.in_(ids), Contact.org_id == org_id)
    )
    return int(result.rowcount or 0)


# Counts across the three FK-RESTRICT tables that block a contact delete
# (tbl_leads / tbl_appointments / tbl_walk_ins — the only RESTRICT
# targets on tbl_contacts). Kept as one round-trip via a SELECT of three
# scalar subqueries so the failure-message enumeration on a bulk
# 25-contact delete stays a single query, not three.
_CONTACT_BLOCKER_COUNT_SINGLE_SQL = text(
    "SELECT "
    "(SELECT count(*) FROM tbl_leads WHERE contact_id = :cid) AS leads, "
    "(SELECT count(*) FROM tbl_appointments WHERE contact_id = :cid) AS appointments, "
    "(SELECT count(*) FROM tbl_walk_ins WHERE contact_id = :cid) AS walk_ins"
)

_CONTACT_BLOCKER_COUNT_BULK_SQL = text(
    "SELECT "
    "(SELECT count(*) FROM tbl_leads "
    "  WHERE contact_id = ANY(:ids) AND org_id = :org) AS leads, "
    "(SELECT count(*) FROM tbl_appointments "
    "  WHERE contact_id = ANY(:ids) AND org_id = :org) AS appointments, "
    "(SELECT count(*) FROM tbl_walk_ins "
    "  WHERE contact_id = ANY(:ids) AND org_id = :org) AS walk_ins"
)


async def count_delete_blockers_for_contact(
    session: AsyncSession, contact_id: uuid.UUID
) -> dict[str, int]:
    """How many leads / appointments / walk-ins currently point at this contact.

    Used by the delete conflict handler to build a message that names
    the specific dependency counts instead of the generic 'may have
    linked leads, appointments, or walk-ins' fallback.
    """
    row = (
        await session.execute(_CONTACT_BLOCKER_COUNT_SINGLE_SQL, {"cid": str(contact_id)})
    ).one()
    return {"leads": int(row.leads), "appointments": int(row.appointments), "walk_ins": int(row.walk_ins)}


async def count_delete_blockers_for_contacts(
    session: AsyncSession, *, ids: list[uuid.UUID], org_id: uuid.UUID
) -> dict[str, int]:
    """Bulk variant — aggregate counts across a batch of contact ids.
    Scoped by org_id to match the delete WHERE clause (belt to RLS)."""
    if not ids:
        return {"leads": 0, "appointments": 0, "walk_ins": 0}
    row = (
        await session.execute(
            _CONTACT_BLOCKER_COUNT_BULK_SQL,
            {"ids": [str(i) for i in ids], "org": str(org_id)},
        )
    ).one()
    return {"leads": int(row.leads), "appointments": int(row.appointments), "walk_ins": int(row.walk_ins)}


async def bulk_append_tag(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    tag: str,
    org_id: uuid.UUID,
    max_tags: int = 32,
) -> int:
    """Append `tag` to each contact's `tags` array (if missing).

    Postgres `array_append` keeps the operation atomic per row.
    Rows whose current `tags` length is already at `max_tags` are
    skipped — mirrors the create/update schema cap so this endpoint
    can't quietly grow rows past the intended bound.
    Returns rowcount.
    """
    if not ids:
        return 0
    result = await session.execute(
        sa_update(Contact)
        .where(Contact.id.in_(ids), Contact.org_id == org_id)
        .where(~Contact.tags.contains([tag]))
        .where(
            func.array_length(Contact.tags, 1).is_(None)
            | (func.array_length(Contact.tags, 1) < max_tags)
        )
        .values(tags=func.array_append(Contact.tags, tag))
    )
    return int(result.rowcount or 0)


async def find_duplicate_candidates(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    phone_suffix: str | None,
    email_lower: str | None,
    exclude_id: uuid.UUID | None,
    limit: int = 10,
) -> list[Contact]:
    """Return contacts matching either the last-10-digit phone suffix
    or the lower(email) — within one org. Empty input → empty list."""
    or_filters: list[ColumnElement[bool]] = []
    if phone_suffix:
        or_filters.append(
            func.regexp_replace(Contact.phone, r"\D", "", "g").like(f"%{phone_suffix}")
        )
    if email_lower:
        or_filters.append(func.lower(Contact.email) == email_lower)
    if not or_filters:
        return []
    stmt = (
        select(Contact)
        .where(Contact.org_id == org_id)
        # Anonymised rows carry a placeholder full_name and null
        # phone/email — surfacing them as "possible duplicates" in the
        # create/edit modal is misleading (operator could click
        # through to a wiped record).
        .where(Contact.anonymised_at.is_(None))
        .where(or_(*or_filters))
        .order_by(Contact.created_at.desc())
        .limit(limit)
    )
    if exclude_id is not None:
        stmt = stmt.where(Contact.id != exclude_id)
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def count_contacts_filtered(
    session: AsyncSession,
    *,
    q: str | None,
    sources: list[str] | None,
    tags: list[str] | None,
    assigned_to_ids: list[uuid.UUID] | None,
    custom_filters: Iterable[tuple[str, str]],
) -> int:
    """Total contacts matching the filter set — used by CSV-export cap."""
    filters = _build_filters(
        q=q,
        sources=sources,
        tags=tags,
        assigned_to_ids=assigned_to_ids,
        custom_filters=custom_filters,
    )
    stmt = select(func.count()).select_from(Contact)
    if filters:
        stmt = stmt.where(and_(*filters))
    return int((await session.execute(stmt)).scalar_one())


async def find_birthdays_on(
    session: AsyncSession,
    *,
    month: int,
    day: int,
) -> list[Contact]:
    """Return every Contact whose ``date_of_birth`` matches the
    ``(month, day)`` pair — used by the Step-12 daily birthday scan
    (``core.automation.scheduler.scan_birthdays``).

    The scanner is cross-tenant — it opens a session WITHOUT setting
    ``RequestContext.org_id`` so the ``do_orm_execute`` tenant filter
    is a no-op + the scan returns every org's birthdays in one pass.
    The caller reads ``contact.org_id`` off each row + supplies it
    when publishing the per-org ``contact.birthday`` event.

    Leap-day birthdays (Feb 29) are handled by matching the literal
    pair — in non-leap years those contacts simply don't surface;
    the operator can choose to add a "rolled to Mar 1" condition in
    the trigger if desired.
    """
    stmt = (
        select(Contact)
        .where(Contact.date_of_birth.is_not(None))
        .where(func.extract("month", Contact.date_of_birth) == month)
        .where(func.extract("day", Contact.date_of_birth) == day)
    )
    return list((await session.execute(stmt)).scalars().all())


async def reassign_contact_references(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    primary_id: uuid.UUID,
    secondary_id: uuid.UUID,
) -> tuple[dict[str, int], list[uuid.UUID]]:
    """Repoint every cross-module row that references ``secondary_id``
    to ``primary_id`` inside the given org.

    Called by ``service.merge_contacts`` right before the secondary row
    is deleted. Every UPDATE is org-scoped even though the FK alone
    would guarantee isolation — belt + suspenders, matches every other
    DAL statement in the codebase.

    Returns ``(counts, moved_lead_ids)``:

    - ``counts`` — per-table row-count map (``{"activities": 3,
      "leads": 1, ...}``) so the service can render a "merged X
      activities + Y leads" audit line.
    - ``moved_lead_ids`` — the ids of leads whose ``contact_id`` was
      re-pointed. The service writes a per-lead attribution
      Activity ("This lead was originally on 'Anjali Desai'…") on
      each so the operator can identify what came from the merge
      when they open the lead's timeline. Kept out of ``counts`` so
      the return shape stays simple — no other DAL caller needs
      per-row ids.

    Tables covered (grouped by relationship shape):

    * **Direct FK columns.** appointments · leads · walk-ins · calls ·
      campaign_messages · conversations · reviews · automation_runs ·
      workflow_runs · invoices · consent_events ·
      email_sequence_enrollments · whatsapp_flow_submissions ·
      custom_orders (furniture pack) — a straight UPDATE ... WHERE
      contact_id = :secondary.
    * **Polymorphic entity refs.** activities · tasks — UPDATE where
      entity_type = 'contact' AND entity_id = :secondary.
    * **Join tables with unique (contact_id, X).** contact_group_members
      — DELETE any row where primary is already a member of that group,
      then UPDATE the rest. Otherwise the UPDATE would violate the
      partial unique index.

    Ordering: reassign group memberships (dedupe-first) before the
    generic UPDATEs so a failed UPDATE on the join table doesn't leave
    a half-merged state. Then the RESTRICT-FK targets so the eventual
    secondary DELETE isn't blocked. Then SET NULL / CASCADE targets.
    Order doesn't affect correctness but keeps the failure surface
    small.

    Missing-table tolerance: every UPDATE first checks the target
    exists via ``to_regclass`` and skips silently if not. Local dev DBs
    that lag on migrations or optional integrations (whatsapp-flows,
    email-sequences) still allow merges to complete rather than 500ing
    with an opaque ``ProgrammingError`` on a table that isn't installed.
    """
    counts: dict[str, int] = {}

    async def _table_exists(table_name: str) -> bool:
        row = (
            await session.execute(
                text("SELECT to_regclass(:t) IS NOT NULL"),
                {"t": table_name},
            )
        ).scalar()
        return bool(row)

    # Group memberships: dedupe (drop secondary rows for groups the
    # primary is already in) then reassign the rest.
    if await _table_exists("tbl_contact_group_members"):
        dedupe_group_members = text(
            """
            DELETE FROM tbl_contact_group_members
            WHERE org_id = :org_id
              AND contact_id = :secondary
              AND group_id IN (
                SELECT group_id FROM tbl_contact_group_members
                WHERE org_id = :org_id AND contact_id = :primary
              )
            """
        )
        counts["contact_group_members_deduped"] = (
            await session.execute(
                dedupe_group_members,
                {"org_id": org_id, "primary": primary_id, "secondary": secondary_id},
            )
        ).rowcount or 0

    # Every direct-FK table shares the same UPDATE shape. Iterate a
    # (table, count-key) list so the map is populated per-table with
    # zero repetition.
    #
    # ``tbl_consent_events`` used to live in this loop but the
    # append-only trigger (0109) forbids UPDATE against it. Handled
    # separately below via INSERT-clone-then-cascade so the merged
    # primary keeps the customer's full consent audit trail.
    _FK_TARGETS: tuple[tuple[str, str], ...] = (
        ("tbl_appointments", "appointments"),
        ("tbl_leads", "leads"),
        ("tbl_walk_ins", "walk_ins"),
        ("tbl_calls", "calls"),
        ("tbl_campaign_messages", "campaign_messages"),
        ("tbl_conversations", "conversations"),
        ("tbl_reviews", "reviews"),
        ("tbl_automation_runs", "automation_runs"),
        ("tbl_invoices", "invoices"),
        ("tbl_email_sequence_enrollments", "email_sequence_enrollments"),
        ("tbl_contact_group_members", "contact_group_members"),
        # WhatsApp Flows submissions. FK is `SET NULL` on delete so the
        # secondary DELETE succeeds without repointing — but that
        # silently loses the customer's flow-submission history. Move
        # it to the primary instead.
        ("tbl_whatsapp_flow_submissions", "whatsapp_flow_submissions"),
        # Same "would silently null on cascade" story. Both are
        # ``ondelete='SET NULL'`` so the secondary DELETE never
        # blocked; they were just being dropped on the floor instead
        # of following the merge.
        ("tbl_workflow_event_waits", "workflow_event_waits"),
        # tasks/workflow-scheduling Step 6 — schedule.contact_id FK
        # is `SET NULL` on cascade too. Without this repoint a
        # scheduled workflow attached to the merged-away contact
        # loses its target instead of following the merged-into
        # primary. Every mature CRM does this.
        ("tbl_workflow_schedules", "workflow_schedules"),
        ("tbl_fp_custom_orders", "fp_custom_orders"),
    )
    moved_lead_ids: list[uuid.UUID] = []
    for tbl, key in _FK_TARGETS:
        if not await _table_exists(tbl):
            continue
        # tbl_leads uses ``RETURNING id`` so the service can annotate
        # each moved lead with a per-lead attribution note; every
        # other table takes the plain UPDATE (we only need the count).
        if tbl == "tbl_leads":
            stmt = text(
                "UPDATE tbl_leads SET contact_id = :primary "
                "WHERE org_id = :org_id AND contact_id = :secondary "
                "RETURNING id"
            )
            result = await session.execute(
                stmt,
                {"org_id": org_id, "primary": primary_id, "secondary": secondary_id},
            )
            returned_ids = [row[0] for row in result.fetchall()]
            moved_lead_ids.extend(returned_ids)
            counts[key] = len(returned_ids)
        else:
            stmt = text(
                f"UPDATE {tbl} SET contact_id = :primary "
                f"WHERE org_id = :org_id AND contact_id = :secondary"
            )
            counts[key] = (
                await session.execute(
                    stmt,
                    {"org_id": org_id, "primary": primary_id, "secondary": secondary_id},
                )
            ).rowcount or 0

    # Consent events — append-only trigger blocks UPDATE, so instead
    # of moving rows we INSERT clones onto the primary preserving
    # every original field including ``recorded_at`` so the merged
    # timeline stays chronologically honest. The secondary rows then
    # get cascade-deleted when the secondary contact is deleted
    # (post 0172 the trigger no longer blocks DELETE).
    #
    # ``id`` is server-generated (gen_random_uuid()) so we omit it and
    # let PG mint a fresh key for each clone; this is important
    # because primary + secondary could theoretically share an id
    # collision if a client bug ever supplied it explicitly (they
    # don't today, but belt-and-suspenders).
    if await _table_exists("tbl_consent_events"):
        clone_stmt = text(
            """
            INSERT INTO tbl_consent_events (
                org_id, contact_id, channel, old_status, new_status,
                source, actor_user_id, ip_address, reason,
                request_evidence, recorded_at
            )
            SELECT
                org_id, :primary, channel, old_status, new_status,
                source, actor_user_id, ip_address, reason,
                request_evidence, recorded_at
            FROM tbl_consent_events
            WHERE org_id = :org_id AND contact_id = :secondary
            """
        )
        counts["consent_events"] = (
            await session.execute(
                clone_stmt,
                {"org_id": org_id, "primary": primary_id, "secondary": secondary_id},
            )
        ).rowcount or 0

    # Workflow runs carry a single subject contact_id.
    if await _table_exists("tbl_workflow_runs"):
        stmt = text(
            "UPDATE tbl_workflow_runs SET contact_id = :primary "
            "WHERE org_id = :org_id AND contact_id = :secondary"
        )
        counts["workflow_runs_contact_id"] = (
            await session.execute(
                stmt,
                {"org_id": org_id, "primary": primary_id, "secondary": secondary_id},
            )
        ).rowcount or 0

    # Polymorphic-entity tables: activities + tasks.
    if await _table_exists("tbl_activities"):
        activities_stmt = text(
            "UPDATE tbl_activities SET entity_id = :primary "
            "WHERE org_id = :org_id "
            "AND entity_type = 'contact' AND entity_id = :secondary"
        )
        counts["activities"] = (
            await session.execute(
                activities_stmt,
                {"org_id": org_id, "primary": primary_id, "secondary": secondary_id},
            )
        ).rowcount or 0

    if await _table_exists("tbl_tasks"):
        tasks_stmt = text(
            "UPDATE tbl_tasks SET related_entity_id = :primary "
            "WHERE org_id = :org_id "
            "AND related_entity_type = 'contact' AND related_entity_id = :secondary"
        )
        counts["tasks"] = (
            await session.execute(
                tasks_stmt,
                {"org_id": org_id, "primary": primary_id, "secondary": secondary_id},
            )
        ).rowcount or 0

    return counts, moved_lead_ids


async def list_contacts_for_export(
    session: AsyncSession,
    *,
    q: str | None,
    sources: list[str] | None,
    tags: list[str] | None,
    assigned_to_ids: list[uuid.UUID] | None,
    custom_filters: Iterable[tuple[str, str]],
) -> list[Contact]:
    """Resolve every matching contact (no pagination) for CSV export.

    Caller is expected to have already gated on `count_contacts_filtered`
    so the result fits in memory.
    """
    filters = _build_filters(
        q=q,
        sources=sources,
        tags=tags,
        assigned_to_ids=assigned_to_ids,
        custom_filters=custom_filters,
    )
    stmt = select(Contact).order_by(Contact.created_at.desc(), Contact.id.desc())
    if filters:
        stmt = stmt.where(and_(*filters))
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def cascade_owner_to_related(
    session: AsyncSession,
    *,
    contact_id: uuid.UUID,
    from_owner_id: uuid.UUID,
    to_owner_id: uuid.UUID | None,
) -> dict[str, int]:
    """Follow-the-pack cascade for contact reassignment.

    Scope is intentionally narrow: only walk-ins and leads follow the
    contact's owner. Tasks and appointments stay per-record — an
    assignee on a task or a meeting is a work assignment that a
    contact-level ownership shuffle shouldn't blindly rewrite.

    When a contact's owner changes from ``from_owner_id`` to
    ``to_owner_id``, this helper reassigns every walk-in and lead
    belonging to the contact **whose current owner still equals
    ``from_owner_id``**. Records intentionally reassigned to a
    different user (reception rep vs. sales rep) are respected —
    the WHERE clause only touches rows that were following the
    contact's owner in the first place.

    Returns per-entity rowcounts so the caller can include them in
    the reassign audit payload / API response.
    """
    counts: dict[str, int] = {"walk_ins": 0, "leads": 0}

    walk_in_result = await session.execute(
        sa_update(WalkIn)
        .where(WalkIn.contact_id == contact_id, WalkIn.assigned_to_id == from_owner_id)
        .values(assigned_to_id=to_owner_id)
    )
    counts["walk_ins"] = int(walk_in_result.rowcount or 0)

    lead_result = await session.execute(
        sa_update(Lead)
        .where(Lead.contact_id == contact_id, Lead.assigned_to_id == from_owner_id)
        .values(assigned_to_id=to_owner_id)
    )
    counts["leads"] = int(lead_result.rowcount or 0)

    return counts


__all__ = [
    "build_contact_list_query",
    "bulk_append_tag",
    "cascade_owner_to_related",
    "count_contacts_filtered",
    "delete_contact_row",
    "delete_contacts_in_org",
    "find_contact_by_email",
    "find_duplicate_candidates",
    "get_contact",
    "get_contact_by_phone",
    "insert_contact",
    "is_user_active_member_of_org",
    "list_contacts_by_ids_in_org",
    "list_contacts_for_export",
    "reassign_contact_references",
]
