"""Auth service: login / refresh / logout.

Each function takes an `AsyncSession` so the router can inject the
test DB via `Depends(get_db)`. No mutable module state.

`org_slug` resolves the tenant for login (default decision noted in
the step file). All queries inside the login flow scope by `org_id`
explicitly — the auto-tenant ORM filter is a no-op here because the
request enters with no tenant context yet (no JWT decoded).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

import logging
from pathlib import Path

from src.app.core import audit
from src.app.core.auth.models import AuthSession
from src.app.core.auth.schemas import (
    LoginResponse,
    OnboardingCompleteRequest,
    OnboardingCompleteResponse,
    RefreshResponse,
    RegisterRequest,
    RegisterResponse,
)
from src.app.core.auth.tokens import ACCESS_TOKEN_TTL, TokenClaims, encode_token
from src.app.core.packs.installer import install as install_pack
from src.app.core.packs.loader import PackLoadError, load_pack
from src.app.core.packs.service import get_catalog
from src.app.core.permissions import role_templates
from src.app.core.permissions.models import Role
from src.app.core.tenants.models import Organization
from src.app.core.tenants.service import create_organization
from src.app.core.users.models import OrganizationMember, User, UserInfo
from src.app.shared.context import RequestContext, reset_context, set_context
from src.app.shared.security.password import hash_password, verify_password


logger = logging.getLogger(__name__)

# Path is relative to the container's WORKDIR (/app). The base pack
# ships with the core CRM and supplies the default Leads pipeline,
# lead sources, and call outcomes any new tenant needs out of the box.
_BASE_PACK_FILE = Path("src/app/packs/base/pack.yaml")


async def _get_org_by_slug(db: AsyncSession, slug: str) -> Organization | None:
    result = await db.execute(select(Organization).where(Organization.slug == slug))
    return result.scalar_one_or_none()


async def _resolve_org_for_email(
    db: AsyncSession, email: str
) -> Organization | None:
    """Find the org by walking email → active membership → org.

    Used when login is called without `org_slug` (the email-only flow).
    Returns None when the email isn't known OR has no active membership —
    the caller treats both as "invalid credentials" to avoid leaking
    which case it was.
    """
    result = await db.execute(
        select(Organization)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .join(UserInfo, UserInfo.member_id == OrganizationMember.user_member_id)
        .where(
            UserInfo.email == email,
            OrganizationMember.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def _get_user_by_email_in_org(
    db: AsyncSession, org_id: uuid.UUID, email: str
) -> User | None:
    # Three-table lookup after DR.7: `tbl_user_info` carries the email,
    # `tbl_organization_members` carries the org membership + active
    # flag, `tbl_user_login` carries auth state. We require the
    # membership to be `is_active=true` so a deactivated user is
    # filtered out even if their auth row is still active.
    result = await db.execute(
        select(User)
        .join(UserInfo, UserInfo.member_id == User.id)
        .join(
            OrganizationMember,
            OrganizationMember.user_member_id == User.id,
        )
        .where(
            UserInfo.email == email,
            OrganizationMember.organization_id == org_id,
            OrganizationMember.is_active.is_(True),
            User.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def login(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    org_slug: str | None,
    ip: str | None = None,
    ua: str | None = None,
) -> LoginResponse:
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
    )

    if org_slug:
        org = await _get_org_by_slug(db, org_slug)
    else:
        org = await _resolve_org_for_email(db, email)
    if org is None:
        # No tenant known → can't attribute to a row, intentionally skip audit.
        raise invalid

    user = await _get_user_by_email_in_org(db, org.id, email)
    if user is None or not user.is_active:
        await audit.log(
            "auth.login.failure",
            org_id=org.id,
            user_id=None,
            before={"email": email, "reason": "unknown_or_inactive_user"},
            ip=ip,
            ua=ua,
        )
        raise invalid
    if not verify_password(password, user.password_hash):
        await audit.log(
            "auth.login.failure",
            org_id=org.id,
            user_id=None,
            before={"email": email, "reason": "bad_password"},
            ip=ip,
            ua=ua,
        )
        raise invalid

    token_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    expires_at = now + ACCESS_TOKEN_TTL

    # `user.id` is the bigint storage PK of `tbl_user_login` (DR.6.3).
    # Every UUID-typed `user_id` FK (AuthSession.user_id → users.id,
    # audit_logs.user_id, JWT `sub`) references the user by the UUID
    # identity preserved in `user.legacy_uuid`.
    user_uuid = user.legacy_uuid

    db.add(
        AuthSession(
            id=token_id,
            org_id=org.id,
            user_id=user_uuid,
            expires_at=expires_at,
            ip=ip,
            ua=ua,
        )
    )
    await db.commit()

    await audit.log(
        "auth.login.success",
        org_id=org.id,
        user_id=user_uuid,
        after={"token_id": str(token_id)},
        ip=ip,
        ua=ua,
    )

    encoded, exp = encode_token(
        user_id=user_uuid, org_id=org.id, token_id=token_id, now=now
    )
    return LoginResponse(access_token=encoded, expires_at=exp)


async def refresh(db: AsyncSession, claims: TokenClaims) -> RefreshResponse:
    """Revoke the current session and issue a fresh JWT with a new token_id."""
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or revoked token",
    )

    session = (
        await db.execute(select(AuthSession).where(AuthSession.id == claims.token_id))
    ).scalar_one_or_none()
    if session is None or session.revoked_at is not None:
        raise invalid

    now = datetime.now(timezone.utc)
    if session.expires_at <= now:
        raise invalid

    # Revoke old, issue new.
    session.revoked_at = now
    new_token_id = uuid.uuid4()
    new_expires_at = now + ACCESS_TOKEN_TTL
    db.add(
        AuthSession(
            id=new_token_id,
            org_id=session.org_id,
            user_id=session.user_id,
            expires_at=new_expires_at,
            ip=session.ip,
            ua=session.ua,
        )
    )
    await db.commit()

    encoded, exp = encode_token(
        user_id=session.user_id,
        org_id=session.org_id,
        token_id=new_token_id,
        now=now,
    )
    return RefreshResponse(access_token=encoded, expires_at=exp)


async def logout(db: AsyncSession, token_id: uuid.UUID) -> None:
    """Idempotent — sets `revoked_at` to now if the row exists and isn't already revoked."""
    now = datetime.now(timezone.utc)
    await db.execute(
        update(AuthSession)
        .where(AuthSession.id == token_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await db.commit()


async def list_user_sessions(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    current_token_id: uuid.UUID,
    limit: int = 50,
) -> list[dict]:
    """Most recent `auth_sessions` rows for one user (newest first).

    Each row carries an `is_current` flag for the JWT making the request
    so the Settings → Login history tab can hide the Sign-out button on
    that row. RLS auto-scopes the underlying SELECT to the caller's org.
    """
    result = await db.execute(
        select(AuthSession)
        .where(AuthSession.user_id == user_id)
        .order_by(AuthSession.created_at.desc())
        .limit(limit)
    )
    rows = list(result.scalars().all())
    return [
        {
            "id": row.id,
            "created_at": row.created_at,
            "expires_at": row.expires_at,
            "revoked_at": row.revoked_at,
            "ip": row.ip,
            "ua": row.ua,
            "is_current": row.id == current_token_id,
        }
        for row in rows
    ]


async def get_user_two_factor_status(
    db: AsyncSession, *, member_id: int
) -> tuple[bool, str | None]:
    """Read `(enabled, method)` from `tbl_user_login` for the given user.

    Goes through the legacy `UserLogin` mapping because the layered
    `User` mapper excludes the `two_factor_*` columns. `member_id` is
    `User.id` (the `tbl_user_login.id` bigint PK).
    """
    from src.models.user import UserLogin

    row = (
        await db.execute(
            select(
                UserLogin.two_factor_enabled,
                UserLogin.two_factor_method,
            ).where(UserLogin.id == member_id)
        )
    ).one_or_none()
    if row is None:
        return False, None
    return bool(row[0]), row[1]


async def revoke_user_session(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
) -> bool:
    """Revoke a specific session belonging to `user_id`.

    Returns True if a row was updated (idempotent — already-revoked is
    treated as a no-op success). 404 surfaced by the router when the
    session id doesn't belong to the user (we don't leak existence —
    same row check as `notifications.mark_read`).
    """
    result = await db.execute(
        select(AuthSession).where(
            AuthSession.id == session_id,
            AuthSession.user_id == user_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        await db.commit()
    return True


async def _email_taken(db: AsyncSession, email: str) -> bool:
    result = await db.execute(select(UserInfo.id).where(UserInfo.email == email))
    return result.scalar_one_or_none() is not None


async def register_with_new_org(
    db: AsyncSession,
    *,
    req: RegisterRequest,
    ip: str | None = None,
    ua: str | None = None,
) -> RegisterResponse:
    """Atomic signup: org + Owner role-template seed + user + membership.

    Either every insert lands or none do. On success returns a JWT for
    the newly-created Owner, ready to be carried by the frontend into
    `/user/dashboard`.
    """
    if await _email_taken(db, req.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    workspace_name = (req.organization_name or "").strip() or (
        f"{req.first_name.strip()}'s Workspace"
    )

    org = await create_organization(
        db,
        name=workspace_name,
        created_via="normal_signup",
        # Legacy single-step flow: the org gets the base template
        # immediately; the pack installer below seeds its defaults.
        template_id="base",
    )

    # Role-template install + base-pack install are both tenant-scoped
    # via the auto-filter; set the request context to the new org so
    # all reads/writes resolve against this org's rows.
    token = set_context(RequestContext(org_id=org.id))
    try:
        installed = await role_templates.install(db, org_id=org.id)
    except role_templates.UnknownPermissionKey as exc:
        await db.rollback()
        reset_context(token)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"role template install failed: {exc}",
        )

    # Base pack — installs the default Leads pipeline + 6 stages, lead
    # sources, call outcomes. Best-effort: if the manifest can't be
    # loaded or the install reports errors, log and continue rather
    # than fail signup. The Owner can re-run `install_pack --pack base`
    # later to recover. (No equivalent admin endpoint exists yet; a
    # follow-up could surface this through the Settings UI.)
    try:
        manifest = load_pack(_BASE_PACK_FILE)
        report = await install_pack(db, org_id=org.id, manifest=manifest)
        if report.errors:
            logger.warning(
                "base pack install reported errors for org %s: %s",
                org.id,
                report.errors,
            )
    except PackLoadError as exc:
        logger.warning("base pack manifest unreadable: %s", exc)
    except Exception:
        logger.exception("base pack install failed for org %s", org.id)

    reset_context(token)

    owner_role = installed.get("owner")
    if owner_role is None:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="role template install did not produce an Owner role",
        )

    # `User` (layered mapper) hides legacy `user_id` / 2FA columns. Bypass
    # the exclusion by inserting via `pg_insert(User)` — same trick the
    # seed scripts use — then fetch the bigint id by `legacy_uuid`.
    user_uuid = uuid.uuid4()
    await db.execute(
        pg_insert(User).values(
            {
                "legacy_uuid": user_uuid,
                "user_id": f"usr_{user_uuid.hex}",
                "password": hash_password(req.password),
                "is_active": True,
                "two_factor_enabled": False,
            }
        )
    )
    bigint_id = (
        await db.execute(
            select(User.id).where(User.legacy_uuid == user_uuid)
        )
    ).scalar_one()

    db.add(
        UserInfo(
            member_id=bigint_id,
            first_name=req.first_name.strip(),
            last_name=req.last_name.strip(),
            email=req.email,
            mobile_no=req.phone,
            is_email_verified=False,
            is_mobile_verified=False,
        )
    )
    db.add(
        OrganizationMember(
            organization_id=org.id,
            user_member_id=bigint_id,
            role_id=owner_role.id,
            status="active",
            is_active=True,
            is_demo=False,
        )
    )

    token_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    expires_at = now + ACCESS_TOKEN_TTL
    db.add(
        AuthSession(
            id=token_id,
            org_id=org.id,
            user_id=user_uuid,
            expires_at=expires_at,
            ip=ip,
            ua=ua,
        )
    )

    await db.commit()

    await audit.log(
        "auth.signup",
        org_id=org.id,
        user_id=user_uuid,
        after={
            "email": req.email,
            "organization_name": org.name,
            "organization_slug": org.slug,
            "role": owner_role.name,
        },
        ip=ip,
        ua=ua,
    )

    encoded, exp = encode_token(
        user_id=user_uuid, org_id=org.id, token_id=token_id, now=now
    )
    return RegisterResponse(
        access_token=encoded,
        expires_at=exp,
        organization_id=org.id,
        organization_slug=org.slug,
        role_name=owner_role.name,
        # Legacy single-step signup ships a fully-set-up org with the
        # base pack installed — onboarding is already done.
        needs_onboarding=False,
    )


# --- Step 2: split signup + onboarding -----------------------------------
#
# `register_user_only` and `complete_onboarding` together implement the
# two-stage flow the onboarding picker needs. They share the user-create
# primitives with `register_with_new_org` above but defer pack selection
# (and the matching pack install) to the onboarding endpoint.
#
# Architectural note: the spec called for a JWT carrying
# `needs_onboarding=true` and *no* org. But `AuthSession` is TenantScoped
# (RLS-enforced) and `encode_token` requires `org_id` — issuing a
# tokenless flow would require schema + RLS changes well outside Step 2.
# Pivot: create the org during register with `template_id="pending"`,
# install role templates so a real Owner role + membership exist, issue
# a normal JWT. The onboarding endpoint then *finalizes* the org
# (rename, set template_id, run pack installer) and rotates the JWT.
# `needs_onboarding` derives server-side from `org.template_id == "pending"`
# in `/users/me` — same UX, no JWT schema change.

PENDING_TEMPLATE_ID = "pending"


async def register_user_only(
    db: AsyncSession,
    *,
    req: RegisterRequest,
    ip: str | None = None,
    ua: str | None = None,
) -> RegisterResponse:
    """Self-signup stage 1: create the user + a pending-template org.

    Inserts a placeholder organization with `template_id="pending"`
    (no pack data seeded). Role templates land so an Owner role +
    active membership exist; the resulting JWT is a normal admin
    token. The user is expected to call `complete_onboarding` next,
    which renames the org, sets a real `template_id`, and runs the
    matching pack installer.
    """
    if await _email_taken(db, req.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    # Placeholder workspace name — the onboarding page renames it
    # immediately, so the user never sees this string.
    workspace_name = f"{req.first_name.strip()}'s Workspace"

    org = await create_organization(
        db,
        name=workspace_name,
        created_via="normal_signup",
        template_id=PENDING_TEMPLATE_ID,
    )

    token = set_context(RequestContext(org_id=org.id))
    try:
        installed = await role_templates.install(db, org_id=org.id)
    except role_templates.UnknownPermissionKey as exc:
        await db.rollback()
        reset_context(token)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"role template install failed: {exc}",
        )
    reset_context(token)

    owner_role = installed.get("owner")
    if owner_role is None:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="role template install did not produce an Owner role",
        )

    user_uuid = uuid.uuid4()
    await db.execute(
        pg_insert(User).values(
            {
                "legacy_uuid": user_uuid,
                "user_id": f"usr_{user_uuid.hex}",
                "password": hash_password(req.password),
                "is_active": True,
                "two_factor_enabled": False,
            }
        )
    )
    bigint_id = (
        await db.execute(
            select(User.id).where(User.legacy_uuid == user_uuid)
        )
    ).scalar_one()

    db.add(
        UserInfo(
            member_id=bigint_id,
            first_name=req.first_name.strip(),
            last_name=req.last_name.strip(),
            email=req.email,
            mobile_no=req.phone,
            is_email_verified=False,
            is_mobile_verified=False,
        )
    )
    db.add(
        OrganizationMember(
            organization_id=org.id,
            user_member_id=bigint_id,
            role_id=owner_role.id,
            status="active",
            is_active=True,
            is_demo=False,
        )
    )

    token_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    expires_at = now + ACCESS_TOKEN_TTL
    db.add(
        AuthSession(
            id=token_id,
            org_id=org.id,
            user_id=user_uuid,
            expires_at=expires_at,
            ip=ip,
            ua=ua,
        )
    )

    await db.commit()

    await audit.log(
        "auth.signup",
        org_id=org.id,
        user_id=user_uuid,
        after={
            "email": req.email,
            "organization_name": org.name,
            "organization_slug": org.slug,
            "role": owner_role.name,
            "pending_onboarding": True,
        },
        ip=ip,
        ua=ua,
    )

    encoded, exp = encode_token(
        user_id=user_uuid, org_id=org.id, token_id=token_id, now=now
    )
    return RegisterResponse(
        access_token=encoded,
        expires_at=exp,
        organization_id=org.id,
        organization_slug=org.slug,
        role_name=owner_role.name,
        needs_onboarding=True,
    )


def _validate_template_choice(template_id: str) -> dict:
    """Resolve `template_id` against the catalog. Returns the tile
    dict on success. Raises HTTPException 400 for unknown or
    coming-soon templates.
    """
    catalog = get_catalog()
    for tile in catalog.packs:
        if tile.template_id == template_id:
            if tile.status != "available":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": "template_not_available",
                        "message": f"{tile.name} is coming soon.",
                    },
                )
            return tile.model_dump()
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"error": "template_not_found", "template_id": template_id},
    )


async def complete_onboarding(
    db: AsyncSession,
    *,
    user: User,
    current_token_id: uuid.UUID,
    req: OnboardingCompleteRequest,
    ip: str | None = None,
    ua: str | None = None,
) -> OnboardingCompleteResponse:
    """Self-signup stage 2: finalize the pending-template org.

    Renames the org, sets `template_id` from the user's pick, applies
    pack defaults (currency, tax_rate) unless the request overrides
    them, and runs `packs.installer.install` so the chosen vertical's
    pipelines / custom fields / lead sources / call outcomes / org
    settings land. Rotates the JWT so the next response is a normal
    onboarding-complete token. Idempotent: a user whose org is no
    longer in `template_id="pending"` gets 409 (already onboarded).
    """
    tile = _validate_template_choice(req.template_id)

    org = (
        await db.execute(
            select(Organization).where(Organization.id == user.org_id)
        )
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="organization not found",
        )

    if org.template_id != PENDING_TEMPLATE_ID:
        # Already onboarded — single org per signup; second call is a
        # conflict, not a re-install.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "already_onboarded"},
        )

    # Apply user-supplied overrides, else fall back to the catalog
    # tile's defaults. `default_tax_rate` from the catalog is a float;
    # the org column is Numeric — SQLAlchemy coerces on write.
    org.name = req.organization_name.strip()
    org.template_id = req.template_id
    org.currency = req.currency or tile["default_currency"]
    org.tax_rate = tile["default_tax_rate"]

    # Pack install runs in the same transaction; the installer wraps
    # each section in its own try/except internally and reports errors
    # via `InstallReport.errors` rather than raising — so a partial
    # seed is loud but does not roll back the org rename. (Matching
    # the existing `register_with_new_org` policy.)
    manifest_path = Path(f"src/app/packs/{req.template_id}/pack.yaml")
    try:
        manifest = load_pack(manifest_path)
    except PackLoadError as exc:
        # Catalog said this pack was `available` but its manifest is
        # unreadable — fall back to 500 so the user can retry.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"pack manifest unreadable: {exc}",
        )

    ctx_token = set_context(RequestContext(org_id=org.id))
    try:
        report = await install_pack(db, org_id=org.id, manifest=manifest)
        if report.errors:
            logger.warning(
                "pack install reported errors for org %s template %s: %s",
                org.id,
                req.template_id,
                report.errors,
            )
    finally:
        reset_context(ctx_token)

    # Rotate JWT: revoke the current session, issue a new one. The new
    # token reflects the onboarded state so the frontend route guard
    # passes on next navigation.
    now = datetime.now(timezone.utc)
    await db.execute(
        update(AuthSession)
        .where(
            AuthSession.id == current_token_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )

    new_token_id = uuid.uuid4()
    new_expires_at = now + ACCESS_TOKEN_TTL
    db.add(
        AuthSession(
            id=new_token_id,
            org_id=org.id,
            user_id=user.legacy_uuid,
            expires_at=new_expires_at,
            ip=ip,
            ua=ua,
        )
    )

    await db.commit()

    await audit.log(
        "org.created_via_onboarding",
        org_id=org.id,
        user_id=user.legacy_uuid,
        after={
            "org_name": org.name,
            "template_id": req.template_id,
            "country": req.country,
            "currency": org.currency,
            "team_size": req.team_size,
        },
        ip=ip,
        ua=ua,
    )
    await audit.log(
        "pack.installed_via_onboarding",
        org_id=org.id,
        user_id=user.legacy_uuid,
        after={
            "template_id": manifest.template_id,
            "template_version": manifest.version,
            "pipelines_created": report.pipelines_created,
            "custom_fields_created": report.custom_fields_created,
            "roles_created": report.roles_created,
            "errors": report.errors,
        },
        ip=ip,
        ua=ua,
    )

    encoded, exp = encode_token(
        user_id=user.legacy_uuid,
        org_id=org.id,
        token_id=new_token_id,
        now=now,
    )
    role_name = (
        await db.execute(
            select(Role.name).where(Role.id == user.role_id)
        )
    ).scalar_one_or_none() or ""
    return OnboardingCompleteResponse(
        access_token=encoded,
        expires_at=exp,
        organization_id=org.id,
        organization_slug=org.slug,
        role_name=role_name,
    )
