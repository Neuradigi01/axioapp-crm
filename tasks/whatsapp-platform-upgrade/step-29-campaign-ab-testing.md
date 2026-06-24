# Step 29 — Campaign A/B testing

**Goal:** Split a campaign audience between two templates; auto-decide winner by configurable metric (reply / read / click rate); remaining recipients get the winning variant.
**Status:** COMPLETED
**Depends on:** Step 9 (templates), Step 21 (campaign analytics for metric tracking).

---

## Scope

In-scope:
- Extend `tbl_campaigns`:
  - `is_ab_test BOOL DEFAULT FALSE`
  - `variant_a_template_id`, `variant_b_template_id`
  - `split_ratio INT DEFAULT 50` (percent A)
  - `winner_metric` ENUM (`reply_rate` / `read_rate` / `click_rate`)
  - `winner_decided_at TIMESTAMPTZ NULL`
  - `winning_variant CHAR(1) NULL`
- Dispatch logic: random assignment per recipient per split ratio. Persist variant on `tbl_campaign_messages.variant CHAR(1)`.
- Winner decision: after configurable hold-back window (default 24-48 hours), compute metric per variant; pick winner; remaining unsent recipients get winning template.
- Refuse A/B for audience < 50 recipients (statistical noise).
- Frontend campaign create modal: A/B toggle → pick 2 templates + split ratio + winner metric + hold-back window.
- Campaign detail: side-by-side variant comparison; winner banner.

Out of scope:
- Multivariate (>2 variants) — defer.
- A/B on send time — defer.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/campaigns/models.py` | Schema additions |
| `API/alembic/versions/<ts>_campaign_ab.py` | **NEW** |
| `API/src/app/core/campaigns/dispatch.py` | Variant assignment |
| `API/src/app/core/campaigns/ab_decider.py` | **NEW** scheduled winner decision |
| `API/src/app/core/campaigns/router.py` | A/B params accepted on create |
| `API/src/app/core/reporting/campaign_analytics.py` | Per-variant aggregation |
| `APP/.../campaigns/create/ab-test-section.component.ts` | **NEW** |
| `APP/.../campaigns/detail/ab-variant-comparison.component.ts` | **NEW** |
| `API/tests/campaigns/test_ab.py` | **NEW** |

**~9 files. ~500 lines.**

## Plan

1. Migration: 6 columns on campaigns + 1 on campaign_messages.
2. Dispatch: rng per recipient → variant; persist + send.
3. Decider Celery task: after hold-back, compute metric per variant; update winner + send winning template to unsent recipients.
4. Frontend: A/B section conditional in create modal; analytics tab in detail shows comparison.
5. Tests: split distribution, winner math, < 50 audience refusal, hold-back countdown.

## DB changes / migrations

`tbl_campaigns` 6 cols + `tbl_campaign_messages.variant CHAR(1) NULL`.

## Tests

7 pytest + 2 Jest.

## Smoke

```
1. Create campaign with 200 recipients. A/B toggle → pick template A + template B; split 50/50; metric reply_rate; hold-back 24h.
2. Launch → first 100 (50% of total) go A, 100 go B.
3. After hold-back: decider runs; pick variant with higher reply rate.
4. Remaining recipients (in this case 0; would matter in larger split or with hold-back of partial population).
5. Detail page: side-by-side metrics + winner banner.
6. Try A/B with audience of 30 → blocked with "minimum 50".
```

## Risks

- Small samples produce flaky winners — minimum 50 enforced; document.
- If template A gets rejected mid-test, fall back to template B for remaining.

## Self-check (10 rules)

`core/campaigns/` + `core/reporting/`. ✓. org_id preserved. ✓. No custom-field changes. ✓. Static UI. ✓ N/A. No registry change. ✓. Existing campaign perms. ✓. pack.yaml untouched. ✓. 9 files / ~500 lines. ✓. Stop-report. ✓. No TODOs. ✓.

## Stop & report

```
Step 29 — Campaign A/B testing
Files: 9
Verify: variant split + auto-winner + comparison UI + min audience guard.
Tests: 7 pytest + 2 Jest.
Phase 9 (Strategic) complete. WhatsApp Platform Upgrade track closes.
Awaiting "proceed".
```
