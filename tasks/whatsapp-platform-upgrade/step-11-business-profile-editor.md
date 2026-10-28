# Step 11 — Business profile editor

**Goal:** Customer manages WhatsApp Business profile (display name request, description, address, hours, email, websites, vertical, profile photo) entirely from Core CRM. No more Meta 
Business Manager trips. Includes business hours editor (Core-side, used by Step 16 automation) and storage for greeting / away message text (wired by Step 16).
**Status:** COMPLETED
**Depends on:** Phase 1 complete (connected WABA with manageable token).

---

## Scope

In-scope:
- New service `business_profile.py` wrapping Meta Graph API:
  - `GET /{phone_id}/whatsapp_business_profile?fields=about,address,description,email,profile_picture_url,websites,vertical`
  - `POST /{phone_id}/whatsapp_business_profile` to update.
- Schema additions to `tbl_whatsapp_account_configs`:
  - `profile_about VARCHAR(139)`, `profile_description VARCHAR(512)`, `profile_address VARCHAR(256)`, `profile_email VARCHAR(128)`
  - `profile_websites JSONB`, `profile_vertical VARCHAR(64)`, `profile_picture_url VARCHAR(512)`
  - `profile_last_synced_at TIMESTAMPTZ`
  - `business_hours JSONB` (day-of-week schedule used by Step 16)
  - `greeting_message TEXT NULL`, `away_message TEXT NULL` (text storage; automation in Step 16)
- Endpoints:
  - `GET /api/v1/integrations/whatsapp/business-profile` (org-scoped)
  - `PATCH /api/v1/integrations/whatsapp/business-profile`
  - `POST /api/v1/integrations/whatsapp/business-profile/refresh`
  - `POST /api/v1/integrations/whatsapp/business-profile/picture` (multipart upload, sends to Meta)
- New permission `whatsapp.business_profile.manage`.
- New sub-page `/user/whatsapp/business-profile`:
  - Profile photo upload (640×640 recommendation, square crop preview)
  - About line (139 chars), Description (512), Address, Email, Websites (up to 2), Vertical dropdown
  - Refresh from Meta button
  - Business hours editor (day-of-week with open/close, multiple ranges per day, closed days, timezone from org)
  - Greeting message text + variable inserter
  - Away message text + variable inserter
- Audit-log every change with before/after values.

Out of scope:
- Display name change request (separate Meta workflow with review) — surfacing as a side button only in this step; full flow is a follow-up.
- Phone health dashboard — Step 12.
- Automation of greeting / away — Step 16 (this step only stores the text).

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/integrations/whatsapp/business_profile.py` | **NEW** |
| [`API/src/app/core/integrations/whatsapp/models.py`](API/src/app/core/integrations/whatsapp/models.py) | Schema additions |
| `API/alembic/versions/<ts>_whatsapp_business_profile.py` | **NEW** migration |
| [`API/src/app/core/integrations/whatsapp/router.py`](API/src/app/core/integrations/whatsapp/router.py) | New endpoints |
| [`API/src/app/core/integrations/whatsapp/module.py`](API/src/app/core/integrations/whatsapp/module.py) | Register `whatsapp.business_profile.manage` |
| `APP/.../whatsapp/business-profile/business-profile-page.component.ts` | **NEW** |
| `APP/.../whatsapp/business-profile/profile-form.component.ts` | **NEW** |
| `APP/.../whatsapp/business-profile/business-hours.component.ts` | **NEW** |
| `APP/.../whatsapp/business-profile/messages-form.component.ts` | **NEW** (greeting / away storage) |
| [`APP/src/app/features/user/user.routes.ts`](APP/src/app/features/user/user.routes.ts) | Add lazy route |
| `API/tests/integrations/test_whatsapp_business_profile.py` | **NEW** |

**~11 files. ~700 lines.**

## Plan

1. Migration with all new columns + GIN index on `business_hours` if querying.
2. Service: typed Pydantic models for profile shape; Meta GET on connect (extend Phase 1) + on manual refresh.
3. Photo upload: accept multipart, validate dimensions/aspect, push to Meta's resumable-upload endpoint, persist returned URL.
4. Frontend form: signal-driven; live char counts; variable inserter chip ({{contact.first_name}}, {{org.name}}, etc.).
5. Hours editor: per-day row with N intervals; quick "copy Mon to all weekdays" action.
6. Audit log emits diff per field on save.
7. Tests: each endpoint + photo upload happy/fail + audit-log assertion.

## DB changes / migrations

Many columns to one existing table; one migration. Down reverses.

## Tests

6 pytest cases.

## Smoke

```
1. Open /user/whatsapp/business-profile → form prefilled from Meta.
2. Change About to "New showroom open Sundays". Save.
3. Verify in Meta Business Manager that field updated.
4. Upload square photo → preview → save → check WhatsApp Business profile shows new photo.
5. Set business hours Mon-Sat 10:00-19:00, Sun closed. Save.
6. Set greeting message "Hello {{contact.first_name}}, welcome to {{org.name}}!" Save.
7. Audit log shows diff for each save.
8. Refresh from Meta button pulls current state.
9. Sales-Junior without business_profile.manage → page read-only.
```

## Risks

- Meta rate limit: 10 updates/day per phone. Frontend throttles save button if hit.
- Photo must pre-crop to square — provide cropper UI to avoid Meta bouncing.
- Display name changes need separate Meta review — don't include in regular Save flow.

## Self-check (10 rules)

All `core/integrations/whatsapp/`. ✓. org_id + RLS. ✓. Static profile schema (Meta-spec'd). ✓ Rule 3/4 N/A. New sub-page registered via descriptor + route. ✓ Rule 5. New permission registered. ✓ Rule 6. pack.yaml untouched. ✓. 11 files / ~700 lines (at edge — acceptable as cohesive surface). ✓ Rule 8. Stop-report. ✓. No TODOs. ✓.

## Stop & report

```
Step 11 — Business profile editor
Files: 11
Verify: profile edits round-trip to Meta + audit; hours + greeting / away text stored.
Tests: 6 pytest cases.
Next: Step 12 — phone health dashboard.
Awaiting "proceed".
```
