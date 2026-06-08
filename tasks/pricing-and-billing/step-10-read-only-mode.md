# Step 10 — Read-only / archived mode enforcement

**Goal:** A FastAPI middleware that, when the caller's org has `status IN ('read_only', 'past_due', 'archived', 'cancelled')`, blocks every mutating HTTP verb (POST / PUT / PATCH / DELETE) with a 402, except a tight allow-list of endpoints (subscription change, logout, GDPR export). Read endpoints (GET) are never blocked.
**Track:** Pricing and Billing
**Status:** Completed
**Depends on:** Step 3 (entitlement service — provides `is_read_only` flag), Step 6 (lifecycle — sets statuses correctly), Phase 1.6 (auth — middleware needs `org_id` resolved).

---

## Scope

One middleware, an allow-list, and the structured 402 response. The middleware runs before route handlers, after auth. **No new endpoints in this step.**

## Middleware behaviour

```
For every incoming HTTP request:
  1. If method is GET / HEAD / OPTIONS: pass through.
  2. If path is unauthenticated (no JWT): pass through (signup, login, public /plans).
  3. Resolve org_id from JWT.
  4. Load entitlements (cached per-request via Step 3's get_entitlements).
  5. If entitlements.is_read_only is False: pass through.
  6. If path matches the allow-list: pass through.
  7. Else: return 402 with detail.reason = subscription_status (e.g. 'read_only', 'archived').
```

## Allow-list

Endpoints that must remain writable even when the org is in `read_only` / `past_due` / `archived` state, because they are the recovery path or a no-charge action:

| Path pattern | Methods | Why |
|---|---|---|
| `/api/v1/auth/logout` | POST | Logout always allowed |
| `/api/v1/auth/refresh` | POST | Token refresh keeps the user in the session for read access |
| `/api/v1/subscriptions/change` | POST | THE recovery action — let them re-pay |
| `/api/v1/subscriptions/seats` | POST | Adding seats is also a payment-path action |
| `/api/v1/subscriptions/cancel` | POST | Letting them cancel cleanly is correct UX |
| `/api/v1/users/me` | PATCH | Profile edits OK — not org data |
| `/api/v1/users/me/2fa/*` | POST/DELETE | Security settings |
| `/api/v1/users/me/sessions/{id}` | DELETE | Revoking own sessions |
| `/api/v1/exports/*` | POST | GDPR-style exports must remain available — read access is preserved |

The allow-list is **explicit and small**. New routes added to it require a code review note.

## Response shape

```json
HTTP/1.1 402 Payment Required
Content-Type: application/json
{
  "detail": {
    "reason": "read_only",            // or "past_due" | "archived" | "cancelled"
    "subscription_status": "read_only",
    "since": "2026-06-19T10:00:00Z",
    "message": "Your trial has ended. Upgrade to continue using FurnitureCRM.",
    "upgrade_url": "/user/settings/billing"
  }
}
```

For `archived` status, the message is "Your account is archived. Contact support to restore." For `cancelled`, "Your subscription is cancelled."

## Implementation

`api/src/app/core/billing/middleware.py`:

```python
class SubscriptionStateMiddleware(BaseHTTPMiddleware):

    READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

    ALLOWLIST_PATTERNS = [
        re.compile(r"^/api/v1/auth/logout$"),
        re.compile(r"^/api/v1/auth/refresh$"),
        re.compile(r"^/api/v1/subscriptions/change$"),
        re.compile(r"^/api/v1/subscriptions/seats$"),
        re.compile(r"^/api/v1/subscriptions/cancel$"),
        re.compile(r"^/api/v1/users/me$"),
        re.compile(r"^/api/v1/users/me/2fa/.+$"),
        re.compile(r"^/api/v1/users/me/sessions/.+$"),
        re.compile(r"^/api/v1/exports/.+$"),
    ]

    async def dispatch(self, request: Request, call_next):
        if request.method in self.READ_METHODS:
            return await call_next(request)
        if not _is_authenticated(request):
            return await call_next(request)
        if any(p.match(request.url.path) for p in self.ALLOWLIST_PATTERNS):
            return await call_next(request)

        org_id = await _resolve_org_id(request)
        if org_id is None:
            return await call_next(request)

        async with async_session() as session:
            ent = await entitlements.load_for_org(session, org_id)
            if not ent.is_read_only:
                return await call_next(request)
            return _read_only_response(ent.subscription)
```

Registered after the auth middleware in `main.py`.

### Cancellation endpoint

This step delivers the allow-list slot for `POST /api/v1/subscriptions/cancel` — the actual endpoint is a small addition:

```python
@router.post("/subscriptions/cancel")
async def cancel_subscription(...):
    """Marks subscription cancelled. If a Stripe sub exists, also cancels there (Step 13's webhook
    will sync). User loses write access immediately; data preserved per archive timeline."""
```

Owner-only (Step 19 enforces). Idempotent.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/billing/middleware.py` | created — `SubscriptionStateMiddleware` |
| `api/src/app/core/billing/router.py` | modified — `POST /subscriptions/cancel` |
| `api/src/app/core/billing/service.py` | modified — `cancel_subscription(session, org_id)` |
| `api/src/app/main.py` | modified — register middleware after auth |
| `api/tests/core/billing/test_read_only_middleware.py` | created |
| `api/tests/core/billing/test_cancel_subscription.py` | created |

**6 files.** Within rule.

## Tests

`test_read_only_middleware.py`:

- **Read endpoint passes on read_only org:** GET `/api/v1/contacts` → 200.
- **Write endpoint blocked on read_only:** POST `/api/v1/contacts` → 402 with detail.reason='read_only'.
- **Write endpoint blocked on archived:** POST `/api/v1/contacts` → 402 with detail.reason='archived'.
- **Write endpoint blocked on past_due:** POST `/api/v1/contacts` → 402 with detail.reason='past_due'.
- **Allow-list path works on read_only:** POST `/api/v1/subscriptions/change` → handler reached.
- **Allow-list logout works on read_only:** POST `/api/v1/auth/logout` → handler reached.
- **Allow-list profile edit works:** PATCH `/api/v1/users/me` → handler reached.
- **Active subscription passes all routes:** POST `/api/v1/contacts` on active sub → handler reached.
- **Trialing subscription passes write routes:** POST `/api/v1/contacts` on trialing sub → handler reached (trial is NOT read-only).
- **Unauthenticated requests pass:** POST `/api/v1/auth/login` → handler reached (no entitlement check possible).
- **GDPR export allowed:** POST `/api/v1/exports/contacts` → handler reached on read_only.

`test_cancel_subscription.py`:

- **Active → cancelled:** POST cancel → status='cancelled', `cancelled_at` set.
- **Cancel is idempotent:** second cancel → 200, no double-event in audit log.
- **Cancel blocks further writes:** after cancel, POST `/contacts` → 402.
- **Audit event written:** `subscription.cancelled` event lands.
- **Non-owner cannot cancel:** Employee tries → 403 (enforced by Step 19).

## Smoke

```
docker exec template_api-api-1 pytest tests/core/billing/test_read_only_middleware.py -v
docker exec template_api-api-1 pytest tests/core/billing/test_cancel_subscription.py -v

# Force read_only state and confirm middleware:
docker exec -it template_api-api-1 uv run python -c "
import asyncio
from app.shared.db import async_session
async def go():
    async with async_session() as s:
        await s.execute(\"UPDATE subscriptions SET status='read_only', read_only_at=now() WHERE org_id='41f9ede9-41b3-44ce-b489-3004566d4068'\")
        await s.commit()
asyncio.run(go())
"

# Now hit a write endpoint:
TOKEN=...
curl -X POST http://localhost:8000/api/v1/contacts \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"first_name":"Test","last_name":"Person"}'
# → 402 with detail.reason='read_only'

# Hit the recovery path:
curl -X POST http://localhost:8000/api/v1/subscriptions/change \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"to_plan":"basic","billing_cycle":"monthly","seats":5}'
# → 200 needs_payment (handler reached even though org is read_only)

# Restore active state after smoke:
docker exec -it template_api-api-1 uv run python -c "
# UPDATE subscriptions SET status='trialing', read_only_at=null WHERE org_id=...
"
```

## Risks

- **Middleware order matters.** Must run AFTER the auth middleware (otherwise no JWT to resolve org from) and BEFORE per-route handlers. Document in `main.py` with a comment.
- **Per-request DB session for the middleware.** Each read_only check opens a session for the entitlements load. That's one extra round-trip per mutating call on a read_only org. For a healthy org (status='active' or 'trialing'), the middleware short-circuits without DB hit if the auth layer already attached the entitlements to `request.state` — TBD optimization, not required for correctness.
- **Allow-list maintenance.** Adding a new endpoint that should remain writable in read_only mode requires updating this regex list. Easy to forget. Add a `@bypass_read_only` decorator pattern as a follow-up if the list grows past ~15 entries.
- **`past_due` is treated as read_only** — the customer's card was declined and they have a grace period. Stripe handles the dunning emails; our middleware enforces the access block. When the customer pays, the webhook (Step 13) flips status back to `active`.

## Rollback

Revert the 6 files. Middleware is no longer registered → all writes succeed regardless of subscription state. Live read_only customers get write access back temporarily on rollback — communicate before doing this in production.
