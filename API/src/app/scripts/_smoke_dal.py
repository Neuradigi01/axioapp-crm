"""One-off runtime smoke test of the per-module data_access layer.

NOT a pytest target. Run with:
    docker exec crm-api-1 python -m src.app.scripts._smoke_dal
"""

import asyncio
import inspect
import urllib.error as _ue
import urllib.request as _ur
import uuid

import src.app.core.auth.data_access as auth_da
import src.app.core.contacts.data_access as contacts_da
import src.app.core.tenants.data_access as tenants_da
import src.app.core.users.data_access as users_da
import src.app.core.users.service as users_service
from src.app.shared.context import RequestContext, reset_context, set_context
from src.app.shared.db import async_session

SMOKE_ORG_ID = uuid.UUID("41f9ede9-41b3-44ce-b489-3004566d4068")
SMOKE_EMAIL = "ajaygogane224@gmail.com"


def hr(title: str) -> None:
    print("=" * 70)
    print(title)
    print("=" * 70)


def step(ok: bool, msg: str) -> bool:
    print(f"  [{'OK' if ok else 'FAIL'}] {msg}")
    return ok


def main() -> int:
    failures = 0
    hr("1) PUBLIC SURFACE CHECK")
    expected = {
        "users.data_access": (
            users_da,
            {
                "get_user_by_uuid",
                "get_user_by_email",
                "get_user_info",
                "email_exists",
                "get_membership",
                "require_membership",
                "count_active_members",
                "get_role_in_org",
                "get_role_by_id_in_org",
                "get_owner_role",
                "get_admin_role",
                "list_open_record_ids",
                "compute_open_records_counts",
                "assert_not_owner_role",
            },
        ),
        "tenants.data_access": (tenants_da, {"get_organization_by_id", "get_organization_by_slug"}),
        "auth.data_access": (auth_da, {"get_auth_session"}),
        "contacts.data_access": (contacts_da, {"get_contact", "get_contact_by_phone"}),
    }
    for name, (mod, wanted) in expected.items():
        actual = {n for n in dir(mod) if not n.startswith("_")}
        actual -= {"users", "memberships", "organizations", "auth_sessions", "contacts"}
        missing = wanted - actual
        extra = actual - wanted
        ok = not missing and not extra
        if not ok:
            failures += 1
        suffix = ""
        if missing:
            suffix += f" MISSING {sorted(missing)}"
        if extra:
            suffix += f" EXTRA {sorted(extra)}"
        step(ok, f"{name}: {len(actual)}/{len(wanted)} exports{suffix}")

    hr("2) CALLABLE CHECK")
    for name, (mod, wanted) in expected.items():
        bad = [fn for fn in wanted if not inspect.iscoroutinefunction(getattr(mod, fn))]
        ok = not bad
        if not ok:
            failures += 1
        step(ok, f"{name}: all coroutines" + (f" — non-coroutine: {bad}" if bad else ""))

    hr("3) LIVE DB EXERCISE (Ajay's Workspace)")

    async def db_exercise() -> int:
        local_failures = 0
        async with async_session() as s:
            org = await tenants_da.get_organization_by_id(s, SMOKE_ORG_ID)
            if not step(
                org is not None and org.id == SMOKE_ORG_ID,
                f"tenants.get_organization_by_id -> {org.name if org else None!r}",
            ):
                local_failures += 1
            if org is None:
                return local_failures
            o2 = await tenants_da.get_organization_by_slug(s, org.slug)
            if not step(
                o2 is not None and o2.id == SMOKE_ORG_ID,
                f"tenants.get_organization_by_slug({org.slug!r}) -> {o2.id if o2 else None}",
            ):
                local_failures += 1

            user = await users_da.get_user_by_email(s, SMOKE_EMAIL)
            if not step(
                user is not None and user.legacy_uuid is not None,
                f"users.get_user_by_email({SMOKE_EMAIL!r}) -> uuid={user.legacy_uuid if user else None}",
            ):
                local_failures += 1
                return local_failures
            user_uuid = user.legacy_uuid

            u2 = await users_da.get_user_by_uuid(s, user_uuid)
            if not step(
                u2 is not None and u2.id == user.id,
                f"users.get_user_by_uuid({user_uuid}) -> id={u2.id if u2 else None}",
            ):
                local_failures += 1

            u3 = await users_da.get_user_by_email(
                s, SMOKE_EMAIL, org_id=SMOKE_ORG_ID, active_only=True
            )
            if not step(
                u3 is not None and u3.id == user.id,
                f"users.get_user_by_email(org-scoped, active_only=True) -> id={u3.id if u3 else None}",
            ):
                local_failures += 1

            info = await users_da.get_user_info(s, user.id)
            if not step(
                info is not None and info.email == SMOKE_EMAIL,
                f"users.get_user_info({user.id}) -> email={info.email if info else None}",
            ):
                local_failures += 1

            if not step(
                await users_da.email_exists(s, SMOKE_EMAIL) is True,
                f"users.email_exists({SMOKE_EMAIL!r}) -> True",
            ):
                local_failures += 1
            if not step(
                await users_da.email_exists(s, "nobody@nowhere.invalid") is False,
                "users.email_exists(invalid email) -> False",
            ):
                local_failures += 1

            mem = await users_da.get_membership(s, user_member_id=user.id, org_id=SMOKE_ORG_ID)
            if not step(
                mem is not None and mem.is_active,
                f"users.get_membership -> active={mem.is_active if mem else None}, role_id={mem.role_id if mem else None}",
            ):
                local_failures += 1
                return local_failures

            u_, m_ = await users_service.require_membership(
                s, user_uuid=user_uuid, org_id=SMOKE_ORG_ID, active_only=True
            )
            if not step(
                u_.id == user.id and m_.id == mem.id,
                f"users.require_membership(active_only=True) -> (u={u_.id}, m={m_.id})",
            ):
                local_failures += 1

            seats = await users_da.count_active_members(s, SMOKE_ORG_ID)
            if not step(seats >= 1, f"users.count_active_members(org) -> {seats}"):
                local_failures += 1

            owner = await users_da.get_owner_role(s, SMOKE_ORG_ID)
            if not step(
                owner is not None and owner.name == "Owner" and owner.is_system,
                f"users.get_owner_role -> {owner.name if owner else None} is_system={owner.is_system if owner else None}",
            ):
                local_failures += 1

            admin = await users_da.get_admin_role(s, SMOKE_ORG_ID)
            step(
                True,
                f"users.get_admin_role -> {admin.name if admin else None} (may be None if Owner deleted Admin row)",
            )

            r_ = await users_service.get_role_in_org(s, role_id=mem.role_id, org_id=SMOKE_ORG_ID)
            if not step(r_ is not None, f"users.get_role_in_org(current role) -> {r_.name}"):
                local_failures += 1
            r_none = await users_da.get_role_by_id_in_org(
                s, role_id=uuid.uuid4(), org_id=SMOKE_ORG_ID
            )
            if not step(r_none is None, f"users.get_role_by_id_in_org(random uuid) -> {r_none}"):
                local_failures += 1

            token = set_context(RequestContext(org_id=SMOKE_ORG_ID, user_id=user_uuid))
            try:
                counts = await users_da.compute_open_records_counts(
                    s, user_uuid=user_uuid, org_id=SMOKE_ORG_ID
                )
                if not step(
                    all(
                        k in counts
                        for k in ("contacts", "leads", "walk_ins", "appointments", "tasks", "total")
                    ),
                    f"users.compute_open_records_counts -> {counts}",
                ):
                    local_failures += 1

                from fastapi import HTTPException

                raised_403 = False
                try:
                    await users_service.assert_not_owner_role(
                        s, user_uuid=user_uuid, org_id=SMOKE_ORG_ID
                    )
                except HTTPException as ex:
                    raised_403 = ex.status_code == 403
                if not step(
                    raised_403,
                    "users.assert_not_owner_role(Owner) raised 403",
                ):
                    local_failures += 1

                # contacts.data_access — pick the first contact in the org if any
                from sqlalchemy import select

                from src.app.core.contacts.models import Contact

                row = (await s.execute(select(Contact.id, Contact.phone).limit(1))).first()
                if row is None:
                    step(
                        True,
                        "contacts: org has zero contacts — by-id/by-phone exercised against None",
                    )
                    none_c = await contacts_da.get_contact(s, uuid.uuid4())
                    if not step(none_c is None, f"contacts.get_contact(random) -> {none_c}"):
                        local_failures += 1
                else:
                    cid, cphone = row
                    c = await contacts_da.get_contact(s, cid)
                    if not step(
                        c is not None and c.id == cid,
                        f"contacts.get_contact({cid}) -> id={c.id if c else None}",
                    ):
                        local_failures += 1
                    if cphone:
                        cp = await contacts_da.get_contact_by_phone(s, cphone)
                        if not step(
                            cp is not None and cp.phone == cphone,
                            f"contacts.get_contact_by_phone({cphone!r}) -> id={cp.id if cp else None}",
                        ):
                            local_failures += 1
                    else:
                        step(True, "contacts: chosen row has no phone — by-phone test skipped")
            finally:
                reset_context(token)

            # auth.data_access — random non-existent token should resolve None
            none_session = await auth_da.get_auth_session(s, session_id=uuid.uuid4())
            if not step(
                none_session is None,
                f"auth.get_auth_session(random uuid) -> {none_session}",
            ):
                local_failures += 1

        return local_failures

    failures += asyncio.run(db_exercise())

    hr("4) LIVE ENDPOINT PROBES")

    def probe(path, method="GET"):
        try:
            req = _ur.Request(f"http://localhost:8000{path}", method=method)
            with _ur.urlopen(req, timeout=10) as resp:
                return resp.status
        except _ue.HTTPError as err:
            return err.code
        except Exception as err:
            return f"ERR: {err}"

    endpoints = [
        ("/api/v1/users/me", "GET", 401),
        ("/api/v1/contacts", "GET", 401),
        ("/api/v1/leads", "GET", 401),
        ("/api/v1/walk-ins", "GET", 401),
        ("/api/v1/appointments", "GET", 401),
        ("/api/v1/tasks", "GET", 401),
        ("/api/v1/staff", "GET", 401),
        ("/api/v1/notifications", "GET", 401),
        ("/api/v1/conversations", "GET", 401),
        ("/api/v1/subscriptions/current", "GET", 401),
        ("/api/v1/invitations", "GET", 401),
        ("/api/v1/permissions", "GET", 401),
        ("/api/v1/campaigns", "GET", 401),
        ("/api/v1/auth/login", "GET", 405),
        ("/docs", "GET", 200),
    ]
    for path, method, want in endpoints:
        got = probe(path, method)
        if not step(got == want, f"{method} {path:42s} -> HTTP {got} (want {want})"):
            failures += 1

    hr("VERDICT")
    print(f"  {'ALL GREEN' if failures == 0 else f'{failures} FAILURE(S)'}")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
