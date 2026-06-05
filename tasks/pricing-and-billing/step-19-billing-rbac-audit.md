# Step 19 — Owner-only RBAC + billing audit events

**Goal:** Register `billing.read` and `billing.manage` permission keys in the core RBAC registry, assign both to Owner by default (and Owner only), gate every mutating billing endpoint server-side with the manage permission, and emit audit events on every billing state change.
**Track:** Pricing and Billing
**Status:** Pending
**Depends on:** Phase 1.5 (RBAC infrastructure — `roles`, `role_permissions`, `permissions`), Phase 1.7 (`audit_logs`), Steps 7–13 (the endpoints to gate and audit).

---

## Scope

Three changes:

1. **Permission registry** — register `billing.read` and `billing.manage` in the core module-registry (Rule 6 — modules register their own permission keys).
2. **Endpoint protection** — every mutating endpoint from Steps 8, 9, 10, 12 checks `billing.manage`. Read endpoints from Step 7 check `billing.read`.
3. **Audit events** — every state change emits a row in `audit_logs`.

## Permission keys

| Key | Granted by default to | Description |
|---|---|---|
| `billing.read` | Owner | Read the current subscription, usage, invoices. |
| `billing.manage` | Owner | Change plan, change seats, cancel, manage payment methods. |

**Both are granted to Owner ONLY by default.** Admin and Employee templates do not get them. Custom roles can be granted them via the existing roles UI (Phase 2.5.3 + RBAC-Ownership track) — but the Owner role itself cannot have these revoked (Owner is locked, per RBAC-Ownership invariants).

The role-templates Step 2 of the RBAC-Ownership track defines the default permission grants. This step's contribution is to ensure those template definitions include `billing.read` + `billing.manage` for Owner and nothing else for Admin / Employee.

## Endpoint protection

| Endpoint | Method | Required permission |
|---|---|---|
| `GET /api/v1/subscriptions/current` | GET | `billing.read` |
| `GET /api/v1/subscriptions/invoices` | GET | `billing.read` |
| `POST /api/v1/subscriptions/change` | POST | `billing.manage` |
| `POST /api/v1/subscriptions/seats` | POST | `billing.manage` |
| `GET /api/v1/subscriptions/seats/preview` | GET | `billing.manage` (technically read-only, but only managers need it) |
| `POST /api/v1/subscriptions/checkout` | POST | `billing.manage` |
| `POST /api/v1/subscriptions/cancel` | POST | `billing.manage` |
| `POST /api/v1/webhooks/stripe` | POST | **no permission check** — Stripe signature is the auth |
| `GET /api/v1/plans`, `GET /api/v1/plans/{code}` | GET | **no permission check** — public |

Enforced via the existing permission dependency from Phase 1.5 / 2.5 (`@requires_permission("billing.manage")` or equivalent). Returns 403 with the standard "Access Denied" body if the user lacks the permission.

## Audit events

Every billing state change writes an `audit_logs` row using the existing audit-event API from Phase 1.7. Event names follow the project's snake-case + dotted convention:

| Trigger | Event name | Actor | Payload (JSON) |
|---|---|---|---|
| Trial subscription created on signup (Step 6) | `subscription.created` | `system` | `{plan: "trial", trial_ends_at: ...}` |
| Plan change (Step 8) — outcome=scheduled | `subscription.change_scheduled` | the Owner | `{from_plan, to_plan, billing_cycle, effective_at}` |
| Plan change (Step 8) — outcome=needs_payment, before redirect | `subscription.checkout_initiated` | the Owner | `{to_plan, billing_cycle, seats, session_id}` |
| Stripe checkout completed (Step 13) | `subscription.upgraded` | `system` (webhook-triggered) | `{from_plan, to_plan, billing_cycle, seats, stripe_subscription_id}` |
| Seat change (Step 9) — scheduled | `seats.change_scheduled` | the Owner | `{from_seats, to_seats, effective_at}` |
| Seat change (Step 9) — paid | `seats.changed` | `system` (after webhook) | `{from_seats, to_seats}` |
| Payment received (Step 13) | `payment.succeeded` | `system` | `{amount_cents, invoice_id}` |
| Payment failed (Step 13) | `payment.failed` | `system` | `{amount_cents, invoice_id, attempt: N}` |
| Trial expired (Step 6) | `trial.expired` | `system` | `{}` |
| Status → read_only (Step 6) | `subscription.read_only` | `system` | `{from_status}` |
| Status → archived (Step 6) | `subscription.archived` | `system` | `{}` |
| Cancellation (Step 10) | `subscription.cancelled` | the Owner | `{cancelled_at, reason?: free-text}` |
| Org deleted at archive expiry (Step 6) | `org.deleted` | `system` | `{}` |

The events feed into the existing audit-log infrastructure — the audit-log viewer UI is not in scope here (planned for a future phase).

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/billing/permissions.py` | created — registers `billing.read`, `billing.manage` in the core module registry |
| `api/src/app/core/billing/router.py` | modified — wrap each endpoint with the relevant `@requires_permission(...)` |
| `api/src/app/core/billing/webhooks/router.py` | modified — confirm NO permission check (signature-based auth) |
| `api/src/app/core/billing/service.py` | modified — call `audit.emit(...)` at every state-change site |
| `api/src/app/core/billing/lifecycle.py` | modified — emit audit events on transitions |
| `api/src/app/core/billing/webhooks/handlers/*.py` | modified — emit audit events |
| `api/src/app/core/billing/signup_hook.py` | modified — emit `subscription.created` |
| `api/src/app/core/auth/role_templates/templates.py` (or equivalent in RBAC-Ownership Step 2) | modified — add `billing.read`, `billing.manage` to Owner template |
| `api/tests/core/billing/test_billing_rbac.py` | created |
| `api/tests/core/billing/test_billing_audit_events.py` | created |

**10 files.** At the edge of the per-step rule. Most edits are 1-2 lines each — a single audit call per existing function.

## Tests

`test_billing_rbac.py`:

- **Owner can read:** Owner JWT → GET `/subscriptions/current` → 200.
- **Admin cannot read:** Admin JWT → 403.
- **Employee cannot read:** 403.
- **Custom role with `billing.read` granted:** custom role + grant → 200.
- **Owner can manage:** Owner → POST `/subscriptions/change` → 200 (or 400 validation but not 403).
- **Admin cannot manage:** Admin → POST → 403.
- **Webhook accepts without auth:** POST `/webhooks/stripe` with valid signature → 200; without auth header → also 200 (signature is the auth).
- **Public plans endpoint is unauth:** GET `/api/v1/plans` without JWT → 200.

`test_billing_audit_events.py`:

- **Signup emits `subscription.created`:** complete signup → query `audit_logs` for the new org → row exists with event_name='subscription.created', actor='system'.
- **Plan change emits scheduled or initiated:** scheduled change → `subscription.change_scheduled` written; needs_payment → `subscription.checkout_initiated` written, actor=Owner's user_id.
- **Webhook emits upgraded:** simulate `checkout.session.completed` → `subscription.upgraded` written, actor='system'.
- **Trial expiry emits two events:** force lifecycle transition → both `trial.expired` and `subscription.read_only` rows present.
- **Cancellation emits cancelled:** POST cancel → `subscription.cancelled` row, actor=Owner.
- **Audit best-effort:** monkey-patch `audit.emit` to raise → the billing action still succeeds (per the existing best-effort contract from Phase 1.7).

## Smoke

```
.\API\docker-helper.cmd up
docker exec template_api-api-1 pytest tests/core/billing/test_billing_rbac.py -v
docker exec template_api-api-1 pytest tests/core/billing/test_billing_audit_events.py -v

# End-to-end (need an Admin user in Ajay's Workspace):
# As Owner (Ajay): GET /api/v1/subscriptions/current → 200 with full data.
# As Admin: GET /api/v1/subscriptions/current → 403 with structured access-denied body.

# Audit log inspection:
.\API\docker-helper.cmd shell-db
SELECT event_name, actor_user_id, payload, created_at
FROM audit_logs
WHERE org_id = '41f9ede9-41b3-44ce-b489-3004566d4068'
  AND event_name LIKE 'subscription.%' OR event_name LIKE 'payment.%' OR event_name LIKE 'trial.%'
ORDER BY created_at DESC LIMIT 20;
# → Rows from signup, any state changes, etc.
```

## Risks

- **Permission key drift.** If a new billing endpoint is added later (e.g. download specific invoice), reviewer must remember to wrap with `@requires_permission`. Use a CI lint pattern: every route under `/subscriptions/*` must have a permission decorator or be on a documented unauth allow-list (the webhook). Out of scope to implement the lint; document the convention.
- **Audit blast.** Every webhook event triggers an audit row. A spammy retry loop could write hundreds. The audit infra should be tolerant — and webhook dedup from Step 13 means the same Stripe event_id is processed once.
- **Role-template edit conflict.** This step modifies the Owner template defined by RBAC-Ownership Step 2. Ensure those two steps land in the correct order — RBAC-Ownership Step 2 first (creates the template registry), then this step (adds billing keys to Owner). If RBAC-Ownership Step 2 hasn't shipped, defer the template edit here and document a follow-up.

## Rollback

Revert the 10 files. Permission keys disappear; endpoints lose their auth checks (Stripe-signature-based webhook is unaffected). Audit events stop firing. Existing audit rows remain. If permissions were assigned to custom roles by users, those grants are now meaningless rows pointing to a missing key — harmless but should be cleaned up post-rollback.
