# Step 3.16 — Marketing / Campaigns: frontend

**Goal:** Marketing & Campaigns page matching the screenshot. Create Campaign modal. Per-campaign metrics cards.
**Phase:** 3
**Depends on:** 3.15
**Status:** Pending

## Scope
**In-scope:**
- `app/src/app/features/user/core/campaigns/`:
  - `campaigns-api.service.ts`
  - `campaigns.page.ts/.html` — list of campaign cards with stats badges.
  - `create-campaign-modal.component.ts/.html` — channel picker, name, audience builder (reuses contact filter UI from 2.5), template/text, schedule_at.
  - `campaign-detail.page.ts/.html` — stats + per-message table.
- Tailwind only.

## Files to touch
- `app/src/app/features/user/core/campaigns/*` (created)

## Plan
1. Audience builder uses the same filter chips as Contacts list.
2. Schedule_at uses native datetime-local input.
3. Card shows status, channel icon, sent/delivered/read counters.
4. Detail page: list of CampaignMessages with status pills + retry on failed.

## Verification checklist
**Frontend:**
- create campaign → list updated.
- start → status transitions; counters update via polling (5s).

## Self-check (10 rules)
- [ ] Tailwind only.

## Stop & report
Await "proceed" before Step 3.17.
