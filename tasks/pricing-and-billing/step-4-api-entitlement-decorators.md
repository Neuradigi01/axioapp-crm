# Step 4 — API entitlement decorators

**Goal:** Wrap any FastAPI route with `@requires_feature("...")` or `@enforces_cap("...")` to declaratively gate that route by the caller's plan. Calls into Step 3's `Entitlements` service, returns HTTP 402 with structured detail when the gate fails.
**Track:** Pricing and Billing
**Status:** Pending
**Depends on:** Step 3 (entitlement service). Phase 1.6 (auth) — needs `get_current_org_id` to know whose entitlements to load.

---

## Scope

Two decorators, one Pydantic error response model, and a small set of feature-key constants. **No routes are gated by this step** — that's done case-by-case in Phase 5 when the actual Standard features land. This step just delivers the mechanism.

## The decorators

```python
# api/src/app/core/billing/decorators.py

def requires_feature(key: str):
    """
    Route decorator. Resolves the caller's Entitlements via dependency injection,
    raises EntitlementError(reason='feature_locked', required_plan=...) if the plan
    does not grant the feature.

    Usage:
        @router.post("/automation/workflows")
        @requires_feature("automation.workflows")
        async def create_workflow(...):
            ...
    """

def enforces_cap(resource: str, current_provider: Callable):
    """
    Route decorator. After the handler validates the request but BEFORE the write,
    asks the entitlement service whether adding one more would exceed the cap.

    `current_provider` is an awaitable that returns the current count for the
    resource (e.g. async def contacts_count(org_id) -> int).

    Raises EntitlementError(reason='cap_reached', resource=..., cap=...) if at limit.

    Usage:
        @router.post("/contacts")
        @enforces_cap("contacts", current_provider=count_org_contacts)
        async def create_contact(...):
            ...
    """
```

## Behaviour

- Both decorators are async-aware (work with FastAPI's `async def` handlers).
- They run **after** FastAPI's own dependency resolution (auth, org-id, etc.) and **before** the handler body.
- On failure, raise `EntitlementError` (the HTTP 402 exception from Step 3) — FastAPI's exception handler renders it to the structured JSON.
- They do NOT short-circuit on read-only status alone — that's Step 10's middleware. They only fail on `feature_locked` or `cap_reached`. (A read-only org would also fail Step 10's middleware before getting here, so by the time decorators run, the request is either a write that's allowed or a read.)

## Error response shape

```json
HTTP/1.1 402 Payment Required
Content-Type: application/json
{
  "detail": {
    "reason": "feature_locked",         // | "cap_reached" | "read_only" | "trial_expired"
    "required_plan": "standard",         // null if cap_reached
    "resource": null,                    // "contacts" if cap_reached
    "cap": null,                         // 5000 if cap_reached
    "message": "This feature requires the Standard plan or higher."
  }
}
```

The structured detail lets the frontend (Step 18 — locked tile pattern, Step 17 — upgrade modal) render the right upgrade prompt without parsing strings.

## Feature key constants

`api/src/app/core/billing/feature_keys.py`:

A module of `FEATURE_XYZ = "xyz.abc"` constants, mirroring the keys in `plans.yaml`. Tests assert each constant matches a real plan key. Call sites use the constants:

```python
from app.core.billing.feature_keys import FEATURE_AUTOMATION_WORKFLOWS

@requires_feature(FEATURE_AUTOMATION_WORKFLOWS)
async def create_workflow(...): ...
```

This step delivers the constants module but the actual `@requires_feature` annotations on real routes happen step-by-step as Phase 5 lands those features.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/billing/decorators.py` | created — `requires_feature`, `enforces_cap` |
| `api/src/app/core/billing/feature_keys.py` | created — constants for every key in plans.yaml |
| `api/src/app/core/billing/__init__.py` | modified — re-export decorators for nice imports |
| `api/src/app/main.py` | modified — register `EntitlementError` exception handler if not already done in Step 3 |
| `api/tests/core/billing/test_decorators.py` | created |
| `api/tests/core/billing/test_feature_keys.py` | created — asserts every constant matches a real key |

**6 files.** Within rule.

## Tests

`test_decorators.py`:

- **`requires_feature` blocks on locked plan:** mount a test route `@requires_feature("automation.workflows")`; call as a Basic org user → 402, detail.reason=feature_locked, detail.required_plan=standard.
- **`requires_feature` passes on entitled plan:** same route, Standard org user → 200.
- **`requires_feature` blocks on trial:** trial org calling Standard feature → 402.
- **`enforces_cap` blocks at limit:** mount route gated by `enforces_cap("contacts", count_provider=lambda _: 5000)`, Basic user → 402, detail.reason=cap_reached, detail.cap=5000.
- **`enforces_cap` passes below limit:** same route, `count_provider` returns 4999 → 200.
- **`enforces_cap` allows unlimited:** Enterprise org (cap = -1) → always 200 regardless of count.
- **Stacked decorators work:** route with both `@requires_feature` AND `@enforces_cap` → both must pass; either fails → 402.
- **Decorator preserves async:** wrapping `async def` route does not break FastAPI's await.

`test_feature_keys.py`:

- **Every constant matches a YAML key:** for each `FEATURE_*` constant, assert it appears in `plans.yaml` (across all plans). Catches drift.
- **Every YAML feature key has a constant:** for each key in `plans.yaml`, assert a `FEATURE_*` constant exists with that value. Catches forgotten new features.

## Smoke

```
docker exec template_api-api-1 pytest tests/core/billing/test_decorators.py -v
docker exec template_api-api-1 pytest tests/core/billing/test_feature_keys.py -v
```

A manual end-to-end smoke (mounting a real route and calling it from a Basic user's JWT) is not possible until Step 7's subscription read API lands so we can confirm which org/plan the test user is on. Document this dependency at the top of the test file. Pure unit tests with mocked sessions are enough for Step 4.

## Risks

- **Decorator order matters.** If a route also uses `@router.post(...)`, the FastAPI decorator must be outermost: `@router.post("/x")` then `@requires_feature("k")` then `async def`. Document this in the decorator's docstring.
- **`enforces_cap` runs a DB count on every write.** For high-frequency endpoints (creating events, activities), this is a hot path. Mitigation: the `current_provider` callable can use a denormalized counter from Step 5 (`usage_counters` table) instead of `SELECT COUNT(*)`. Step 5 delivers that.
- **Feature key drift.** Forgetting to update `feature_keys.py` when adding a key to `plans.yaml` would let typos slip in. The `test_feature_keys.py` mutual-check catches it at test time.

## Rollback

Revert the 6 source files. Any routes that adopt the decorators in Phase 5 must be co-rolled-back (they'd start failing without the entitlement module). Track adoption carefully.
