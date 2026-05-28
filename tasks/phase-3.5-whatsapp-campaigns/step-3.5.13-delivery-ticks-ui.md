# Step 3.5.13 — Delivery ticks UI: WhatsApp ✓ / ✓✓ / ✓✓-blue in inbox + campaign detail

**Goal:** Visual feedback for the delivery timestamps captured in Step 3.5.12. Inbox message bubble shows the standard 3-state tick icon; Campaign detail page shows per-row delivered/read status.

**Phase:** 3.5
**Depends on:** 3.5.12 (delivery timestamps populated)
**Status:** PROPOSED — awaiting "begin"

After this step a conversation message looks like:

```
[outbound bubble — "Hi Asha"]               9:42 AM ✓✓
[outbound bubble — "Sale tomorrow"]         9:43 AM ✓✓ (blue)
[outbound bubble — "Reminder"]              9:45 AM ✓
```

And the campaign detail page shows per-row delivery state with a status pill.

---

## Scope

### In-scope

- Message schema extension: include `sent_at`, `delivered_at`, `read_at` in the conversation message read endpoint.
- New computed property `tick_state` derivable client-side:
  - `read_at` present → `read` (blue double tick)
  - `delivered_at` present → `delivered` (grey double tick)
  - `sent_at` present → `sent` (single tick)
  - none → `pending` (clock icon)
- Inbox message bubble component renders tick icons.
- Campaign detail page (new or existing):
  - Per-row table with status pill (Queued / Sent / Delivered / Read / Failed)
  - Header KPIs: total sent, % delivered, % read, % failed
- Live polling: campaign detail page polls every 10s while campaign is `running`.

### Out-of-scope

- Inbound message reaction state → P2.
- Push notifications for "read" → P2.

---

## Files to touch

### Modified (~4)
- `API/src/app/core/conversations/schemas.py` — `MessageRead` adds timestamps
- `API/src/app/core/campaigns/schemas.py` — CampaignMessage read shape extension
- `APP/.../conversations/inbox-message.component.{ts,html}` — tick rendering
- `APP/.../campaigns/campaign-detail.page.{ts,html}` — per-row table + KPIs

**File budget:** ~5 files.

---

## Plan

1. Backend: timestamps already exist; just include in read projection.
2. Frontend ticks: SVG icons (existing Lucide check icons or custom 2-tick SVG). Blue color via Tailwind class.
3. Polling: `interval(10000)` while status is running; cleanup via `takeUntilDestroyed`.

---

## Pre-implementation question

**Q:** Campaign detail page — naya page banaye ya **existing CampaignsListPage** mein expandable row use karen?

- **(a) New page** `/user/campaigns/:id` — proper detail with KPIs + paginated message table
- **(b) Expandable row** in list — quick glance, no page navigation

**Recommendation: (a)** — campaign with 1000+ messages needs paginated table + filters by status, hard to do inline.

---

## Verification + Self-check + Stop & report — standard
