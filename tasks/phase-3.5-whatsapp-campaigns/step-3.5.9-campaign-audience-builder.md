# Step 3.5.9 — Campaign audience builder: Everyone / Group / Filter toggle

**Goal:** Replace the current `audience_filter: {q, source, tag}` modal section with a 3-mode toggle in Campaign Create — "Everyone", "Saved group", "Custom filter" — that produces the same backend payload shape but with much better UX.

**Phase:** 3.5
**Depends on:** 3.5.7 + 3.5.8 (groups exist)
**Status:** ✅ COMPLETED — 69/69 backend tests + Angular build clean

After this step a campaign author opens Create Campaign → audience section shows 3 radio options → picks "Saved group" → dropdown loads groups → pick "Walk-in sofa shoppers" → live count "82 contacts will receive this". Submit serializes `audience_filter = {group_id: "..."}` to backend.

---

## Scope

### In-scope

**Backend:**
- Extend `AudienceFilter` schema to support `{group_id: UUID}` in addition to existing `{q, source, tag}`.
- `resolve_audience(audience_filter)` recognizes `group_id` and delegates to `groups.resolve_group_contacts(group_id)` — both static and dynamic groups supported.
- Backend rejects "both filter AND group_id" combinations (one or the other, not mixed).
- "Everyone" = empty `audience_filter = {}` (already works in existing audience resolver).

**Frontend:**
- Campaign create-modal audience section:
  - Radio toggle: ⚪ Everyone · ⚪ Saved group · ⚪ Custom filter
  - "Everyone": just shows total count "Sends to all 2,348 contacts"
  - "Saved group": dropdown of org's groups (fetched once), live count from group's member_count
  - "Custom filter": existing q/source/tag fields + live count
- Live `preview-size` call debounced 300ms on any change.
- Validation: "Group must be selected" if Saved group mode but no group chosen.

### Out-of-scope

- Exclusion lists ("send to everyone EXCEPT this group") → P2.
- Time-based filters ("created in last 7 days") → P2.

---

## Files to touch

### Modified (~6)
- `API/src/app/core/campaigns/schemas.py` — `AudienceFilter.group_id` optional UUID
- `API/src/app/core/campaigns/service.py` — `resolve_audience` extends
- `API/tests/test_campaigns_audience.py` — group-based test cases
- `APP/.../campaign-create-modal.component.{ts,html}` — audience section rewrite
- `APP/.../campaigns-api.service.ts` — types

**File budget:** ~6 files.

---

## Plan

1. Schema extension is additive — existing filters still work.
2. Frontend toggle stores mode in form, only serializes the relevant fields on submit.
3. Live count uses existing `POST /campaigns/audience/preview` if it exists, else adds one.

---

## Pre-implementation question

**Q:** Mode toggle ka **default** kya rakhein jab modal khulta hai?

- **(a) Everyone** — safest default, operator must explicitly narrow (forces conscious choice)
- **(b) Saved group** — encourages reuse, but a fresh org with no groups sees empty dropdown
- **(c) Custom filter** — old behavior, no change for existing users

**Recommendation: (a)** — for a new feature, "Everyone" prevents accidentally narrow audiences. Operator clearly sees total count and then narrows if needed.

---

## Verification + Self-check + Stop & report — standard
