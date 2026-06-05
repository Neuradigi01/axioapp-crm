# Step 3 — Entitlement service

**Goal:** A small, well-tested Python service that answers two questions for any org: "does this org's plan grant feature X?" and "is this org under the cap for resource Y?" — backed by the plan registry (Step 1) and the active subscription row (Step 2). Used by every gated endpoint in the rest of this track.
**Track:** Pricing and Billing
**Status:** Pending
**Depends on:** Step 1 (plan registry), Step 2 (subscription model). No HTTP yet.

---

## Scope

A `billing.entitlements` module exposing two pure functions and one orchestration class. All synchronous reads (cached). All write-path enforcement runs through this layer — the decorators in Step 4 and the read-only middleware in Step 10 both delegate to this.

## Public surface

```python
# api/src/app/core/billing/entitlements.py

class Entitlements:
    """Carries the effective plan + subscription for one org, computed once per request."""

    org_id: UUID
    plan_code: str               # "trial" | "basic" | "standard" | "enterprise"
    plan: Plan                   # from plans.py registry
    subscription: Subscription   # from billing.models
    status: SubscriptionStatus
    is_read_only: bool           # True iff status in {read_only, archived, cancelled, past_due}
    seats_purchased: int

    def has_feature(self, key: str) -> bool: ...
    def cap_for(self, resource: str) -> int: ...  # returns -1 for unlimited
    def is_within_cap(self, resource: str, current: int) -> bool: ...


async def load_for_org(session, org_id: UUID) -> Entitlements:
    """Look up the active subscription, pull the plan from the registry, return the bundle."""

async def require_feature(session, org_id: UUID, feature_key: str) -> None:
    """Raises EntitlementError(402) if the org's plan does not grant the feature."""

async def require_capacity(session, org_id: UUID, resource: str, current: int) -> None:
    """Raises EntitlementError(402) if adding one more would exceed the cap. Pass current = N-1 to check the (N)th write."""
```

## Behaviour spec

| Method | Returns | Raises |
|---|---|---|
| `Entitlements.has_feature("automation.workflows")` | bool | — |
| `Entitlements.cap_for("contacts")` | int (`-1` = unlimited) | — |
| `Entitlements.is_within_cap("contacts", 5000)` | bool (`current + 1 <= cap`, with `-1` always True) | — |
| `require_feature(session, org_id, "automation.workflows")` | None | `EntitlementError("feature_locked", required_plan="standard")` if false |
| `require_capacity(session, org_id, "contacts", 5000)` | None | `EntitlementError("cap_reached", cap=5000, resource="contacts")` if at limit |

### Subscription-status interaction

The status itself gates writes independent of feature/cap:

| Status | Behaviour |
|---|---|
| `trialing` | Treated as Basic (per founder decision). Trial features = Basic features. |
| `active` | Use plan as defined. Normal operation. |
| `past_due` | Treat as `read_only` for entitlement purposes (no writes) until invoice clears. Read-only behaviour delivered in Step 10. |
| `read_only` | All `require_feature` / `require_capacity` calls raise `EntitlementError("read_only")` for non-read endpoints. Read endpoints unaffected. |
| `archived`, `cancelled` | All write entitlements raise. Read endpoints return their data so the user can export. |

The actual HTTP-level read-only enforcement lives in Step 10's middleware; this service just exposes the *flag* (`is_read_only`) and raises on write-path checks. Step 4's decorators short-circuit if `is_read_only`.

## Caching

Per-request, not per-process. The service is meant to be called from a FastAPI dependency:

```python
async def get_entitlements(
    org_id: UUID = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> Entitlements:
    return await entitlements.load_for_org(session, org_id)
```

The dependency injects once per request — multiple `require_feature` calls inside the same handler use the same loaded bundle, no extra DB hits.

**Process-level cache for the plan registry** is fine and already cached by Step 1. The subscription row is per-org, per-request.

## Error type

`api/src/app/core/billing/exceptions.py`:

```python
class EntitlementError(HTTPException):
    """HTTP 402 Payment Required, with structured detail for the frontend to render upgrade prompt."""

    def __init__(self, reason: Literal["feature_locked", "cap_reached", "read_only", "trial_expired"],
                 required_plan: str | None = None,
                 resource: str | None = None,
                 cap: int | None = None):
        super().__init__(status_code=402, detail={
            "reason": reason,
            "required_plan": required_plan,
            "resource": resource,
            "cap": cap,
        })
```

Frontend reads the structured `detail` to decide which upgrade modal to render.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/billing/entitlements.py` | created — `Entitlements` class + 3 functions |
| `api/src/app/core/billing/exceptions.py` | created — `EntitlementError` |
| `api/src/app/core/billing/dependencies.py` | created — `get_entitlements` FastAPI dependency |
| `api/tests/core/billing/test_entitlements.py` | created — unit tests |

**4 files.** Within rule.

## Tests

`api/tests/core/billing/test_entitlements.py`:

- **Basic plan grants Basic features:** `has_feature("contacts.write") == True`, `has_feature("automation.workflows") == False`.
- **Trial plan grants exactly the same set as Basic:** explicit assertion that for every feature key, `trial.has_feature(key) == basic.has_feature(key)`.
- **Standard unlocks the Standard set:** `has_feature("automation.workflows") == True`, `has_feature("integrations.whatsapp") == True`, `has_feature("sso.saml") == False`.
- **Enterprise unlocks Enterprise set:** `has_feature("sso.saml") == True`, `has_feature("multi_branch") == True`.
- **Cap math:** Basic `cap_for("contacts") == 5000`; `is_within_cap("contacts", 4999) == True`; `is_within_cap("contacts", 5000) == False`.
- **Unlimited sentinel:** Enterprise `cap_for("contacts") == -1`; `is_within_cap("contacts", 999_999_999) == True`.
- **`require_feature` raises with structured detail:** call `require_feature(session, basic_org, "automation.workflows")` → `EntitlementError` raised, `detail["reason"] == "feature_locked"`, `detail["required_plan"] == "standard"`.
- **`require_capacity` raises at the cap:** `require_capacity(session, basic_org, "contacts", 5000)` raises with `detail["reason"] == "cap_reached"`.
- **`is_read_only` reflects status:** `status='read_only'` → `is_read_only == True`. `status='trialing'` → `False`.
- **Unknown feature key:** asking `has_feature("nonexistent.thing")` returns `False` (does not raise). Logs a warning so we catch typos in tests.
- **Unknown plan code on subscription:** `plans.yaml` no longer has `plan_code='oldtier'` but a stale row carries it → `load_for_org` raises a clear `RuntimeError("unknown plan_code 'oldtier'")` — guards against stale data.

## Smoke

```
docker exec template_api-api-1 pytest tests/core/billing/test_entitlements.py -v

# Python REPL in-container:
docker exec -it template_api-api-1 uv run python -c "
from app.core.billing import entitlements, plans
print(plans.get('standard').caps)
print(plans.get('trial').features.get('automation.workflows'))
"
# → trial does NOT have automation; standard's caps include automation_runs_per_month: 5000.
```

## Risks

- **Per-request load is N+1 if abused.** Multiple `require_feature` calls inside one handler must all share the same `Entitlements` instance via dependency injection — never re-load mid-handler. Documented in the module docstring; enforced by code review.
- **Feature key naming drift.** Hardcoded strings (`"automation.workflows"`) are typo-prone. Mitigation: define them as module-level constants in `entitlements.py` (`FEATURE_AUTOMATION_WORKFLOWS = "automation.workflows"`) and use the constants in call sites. Tests assert each constant matches a key in plans.yaml.
- **Cap math off-by-one.** "Can I add one more?" vs "Am I at the cap?" is the common bug. `is_within_cap(resource, current)` is defined as "would `current + 1` still be `<= cap`." Test it both above and below the threshold.

## Rollback

Revert the 4 source files. No DB / migration. Downstream steps (4, 5, 10) that depend on this either revert too or fall back to "no enforcement."
