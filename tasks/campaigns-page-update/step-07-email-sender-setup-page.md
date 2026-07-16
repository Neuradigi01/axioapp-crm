# Step 07 — Email Sender Setup page + bounce suppression pre-flight

**Goal:** New page under the sidebar's Setup group where users verify their sender domains (SPF / DKIM / DMARC) and individual sender addresses. Campaigns can only be started with a verified, DKIM-authenticated mailbox, and hard-bounced addresses are auto-excluded from the audience at start time.
**Track:** Campaigns page update — Email
**Status:** Pending
**Depends on:** Step 03 (mailbox picker), Step 05 (dispatch works), Step 06 (opt-out enforcement — this step layers bounce suppression alongside it)

Screen reference in [`preview.html`](preview.html): **Screen 7 · Email Sender Setup** — verified domains card with SPF / DKIM / DMARC badges + "View DNS records" button, verified sender addresses card, warning banner if none verified.

Also **Screen 4** — the sender-readiness banner ("sales@yourshop.com — Live, DKIM ✓, SPF ✓, DMARC ✓ — ready to send") is populated from this step's data.

---

## Scope

Backend adds a new module `core/email_sender_setup/` (router + service + DAL) mounted at `/api/v1/email-sender-setup/*`, plus one new table for verified domains. Reuses existing `EmailAccount` (single addresses) + `EmailBounce` (bounce records) + `core/email/dkim_spf_check.py` (DNS verification helper — verify this exists during implementation; if not, use `dnspython`).

Backend also extends the campaign `enqueue()` pre-flight with two new blocks: sender-readiness check + bounce suppression.

Frontend adds a new sidebar entry (Owner + Admin only) → new page with two cards (Verified domains, Verified sender addresses) + "Add sender identity" flow.

## Schema

Migration `00XX_email_sender_domain.py` — new table `tbl_email_sender_domains`:

| Column | Type | Constraint |
|---|---|---|
| `id` | UUID | PK |
| `org_id` | UUID | FK → `tbl_organizations.id`, NOT NULL |
| `domain` | TEXT | NOT NULL, unique per org (`UNIQUE(org_id, domain)`) |
| `spf_verified` | BOOLEAN | NOT NULL DEFAULT `false` |
| `dkim_verified` | BOOLEAN | NOT NULL DEFAULT `false` |
| `dmarc_verified` | BOOLEAN | NOT NULL DEFAULT `false` |
| `spf_last_checked_at` | TIMESTAMPTZ | nullable |
| `dkim_last_checked_at` | TIMESTAMPTZ | nullable |
| `dmarc_last_checked_at` | TIMESTAMPTZ | nullable |
| `dkim_selector` | TEXT | NOT NULL — e.g. `core-crm-{org_short_id}` — used to construct the DNS record |
| `dkim_public_key` | TEXT | NOT NULL — generated on domain create |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT `now()` |

Migration `00XX_email_account_verification.py` — extend `tbl_email_accounts`:

| Column | Type | Constraint |
|---|---|---|
| `verified_at` | TIMESTAMPTZ | nullable — set when the address confirms via the verification email |
| `verification_token` | TEXT | nullable — set until consumed |
| `verification_sent_at` | TIMESTAMPTZ | nullable |

Existing `EmailAccount.dkim_enabled` etc. columns (per Step 03's audit) — reuse if present; do NOT duplicate them on the new domain table.

## Backend — new module

`api/src/app/core/email_sender_setup/`

Standard layered layout per CLAUDE.md:

```
email_sender_setup/
├── __init__.py
├── models.py           ← EmailSenderDomain ORM
├── schemas.py          ← Pydantic DTOs
├── router.py           ← 8 endpoints
├── service.py          ← domain + address verification logic
├── data_access.py      ← CRUD
└── dns_check.py        ← reuses core/email/dkim_spf_check.py if it exists, else wraps dnspython
```

### Endpoints (`router.py`)

| Endpoint | Auth | Behaviour |
|---|---|---|
| `GET /email-sender-setup/domains` | Owner + Admin | List verified + pending domains for org |
| `POST /email-sender-setup/domains` | Owner + Admin | Body `{domain}`. Generates DKIM keypair + selector. Returns the row with the DNS records the user must add. |
| `GET /email-sender-setup/domains/{id}/dns-records` | Owner + Admin | Returns the three DNS records (SPF TXT, DKIM CNAME/TXT, DMARC TXT) as `[{type, host, value}]` for copy-paste |
| `POST /email-sender-setup/domains/{id}/verify` | Owner + Admin | Triggers a fresh DNS lookup for all three, updates the row, returns the new status |
| `DELETE /email-sender-setup/domains/{id}` | Owner | Blocks if any `EmailAccount` on this domain is used by a scheduled/running campaign |
| `GET /email-sender-setup/addresses` | Owner + Admin | List `EmailAccount` rows with verification state |
| `POST /email-sender-setup/addresses/{id}/resend-verification` | Owner + Admin | Regenerates token + sends verification email |
| `GET /email-sender-setup/addresses/verify/{token}` | unauthenticated | Consumes a verification token, flips `verified_at` |

### Service layer

- `create_domain_service(org_id, domain)` — validates domain shape (RFC compliant), generates a 2048-bit RSA keypair for DKIM, picks a selector (`core-crm-{org_short_id}`), persists domain row.
- `verify_domain_service(domain_id)` — runs three DNS lookups (SPF, DKIM, DMARC) using `dnspython`. Updates the row + returns the new status. Rate-limited to once per 60 sec per domain per org.
- `list_verified_senders_service(org_id)` — returns a flat list of pickable senders for the campaign create modal (mailbox rows where `sync_state='live'` AND `verified_at IS NOT NULL` AND their domain is fully-verified OR they were verified as standalone addresses).

## Backend — campaign pre-flight (in `campaigns/service.py::enqueue`)

Extend the existing pre-flight block ([around line 306–369](../../api/src/app/core/campaigns/service.py)) with two blocks BEFORE the audience-size guard:

### Sender readiness (Email only)

- Load `campaign.email_account`.
- If `sync_state != 'live'` → block, error message `"Selected mailbox is not connected — reconnect it in Email Sender Setup"`.
- If `verified_at IS NULL` → block, `"Sender address hasn't been verified. Check the verification email."`.
- If the mailbox's domain is not fully-verified (SPF or DKIM missing) → **warn** (not block) by default. Config flag `EMAIL_REQUIRE_FULL_DOMAIN_VERIFICATION` (per-org, default `false`) upgrades warn → block. Reason: DKIM-less sends still work, they just get flagged as promotions or spam. Warn shows a banner on the campaign detail page.

### Bounce suppression (Email only)

- Bulk lookup: for the audience contact ids, find the intersection with `tbl_email_bounce` rows where `bounce_type='hard'` — single query with `IN (...)`, no N+1.
- Auto-exclude those contacts from the audience. Log the count in `Campaign.excluded_bounced_count` (add this integer column in this step's migration if missing).
- Surface the count in the wizard exclusions block ("47 contacts excluded — 3 hard-bounced, 44 opted-out") — the opted-out count comes from Step 06.

## Frontend — new page

Path: `app/src/app/features/user/core/email-sender-setup/`

Files:

- `email-sender-setup.page.ts` + `.html` + `.scss` — the page shell.
- `verified-domains-card.component.ts` + `.html` — list + Add domain + View DNS records modal.
- `verified-addresses-card.component.ts` + `.html` — list + Add address + Resend verification.
- `add-domain-modal.component.ts` + `.html` — new domain flow.
- `dns-records-modal.component.ts` + `.html` — copy-paste-friendly display of SPF/DKIM/DMARC records.

Nav wiring:

- `app/src/app/features/user/user.routes.ts` — new route `/user/email-sender-setup` (or nest under `/user/campaigns/sender-setup`, whichever fits the sidebar registry — pick one, document the choice).
- Sidebar registry entry: label "Email Sender Setup", icon shield-check, permission `email_sender.manage` (Owner + Admin by default).

Wizard integration:

- Update the mailbox picker in the campaign create modal (Step 03) to only offer verified senders — filter comes from `GET /email-sender-setup/addresses?verified=true`.
- Empty state: "No verified sender. Set up in Email Sender Setup." (link).

Campaign detail:

- If the sender's domain has `dkim_verified=false`, show a warning banner: "Sending from an unverified domain — deliverability may suffer. Complete DKIM setup in Email Sender Setup."

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/00XX_email_sender_domain.py` | created |
| `api/alembic/versions/00XX_email_account_verification.py` | created |
| `api/alembic/versions/00XX_campaign_excluded_bounced_count.py` | created |
| `api/src/app/core/email_sender_setup/*.py` | created — new module |
| `api/src/app/core/campaigns/service.py` | modified — pre-flight sender-readiness + bounce suppression |
| `api/src/app/core/campaigns/models.py` | modified — `excluded_bounced_count` column |
| `api/src/app/core/campaigns/send_guard.py` | modified — call the new domain-verification lookup |
| `api/src/app/main.py` | modified — register the new module's router |
| `api/tests/test_email_sender_setup.py` | created |
| `api/tests/test_campaign_email_preflight.py` | created |
| `app/src/app/features/user/core/email-sender-setup/*` | created — page + components + modals |
| `app/src/app/features/user/user.routes.ts` | modified — new route |
| `app/src/app/services/email-sender-setup.service.ts` | created — API client |
| `app/src/app/features/user/core/campaigns/create-campaign-modal.component.{ts,html}` | modified — verified-only mailbox filter + empty state |
| `app/src/app/features/user/core/campaigns/campaign-detail.page.html` | modified — DKIM warning banner |

**~15 files + 3 migrations.** **This step exceeds the per-step rule.** Split into two:

### Recommended split

**07a** — Backend only (**~10 files + 3 migrations**):

- New `email_sender_setup/` module (all files)
- Schema migrations
- Campaign pre-flight extensions in `campaigns/service.py`, `campaigns/models.py`, `campaigns/send_guard.py`
- Router registration in `main.py`
- Both pytest files

**07b** — Frontend only (**~7 files**):

- New Sender Setup page + components + modals + service
- Sidebar registry + route
- Wizard mailbox picker filter + empty state
- Campaign detail DKIM banner

07a can ship without 07b (users just don't see the UI yet). 07b depends on 07a shipping first.

## Tests

`test_email_sender_setup.py`:

- **Domain create:** POST `/email-sender-setup/domains` with `domain=yourshop.com` → 201, keypair generated, DNS records returned.
- **DNS records retrieval:** GET `/…/dns-records` returns the three records with correct hosts + values.
- **Verify — all pass:** mock DNS lookups return valid records → row updated with all three verified.
- **Verify — DKIM missing:** mock returns SPF + DMARC but no DKIM → row shows SPF ✓, DKIM ✗, DMARC ✓.
- **Verify rate limit:** two calls within 60 sec → second returns 429.
- **Address verification token:** GET `/…/addresses/verify/{token}` → address row `verified_at` set. Bad token → 404.
- **Cross-org isolation:** Org A cannot touch Org B's domain rows.
- **Domain delete blocked:** if a scheduled campaign uses an address on this domain → 400.

`test_campaign_email_preflight.py`:

- **Unverified sender blocks start:** campaign with an unverified mailbox → `POST /campaigns/{id}/start` returns 400 with clear reason.
- **Disconnected sender blocks start:** mailbox `sync_state='disconnected'` → 400.
- **DKIM missing warns but allows start:** default org config warns, campaign starts, `campaign.warnings` includes DKIM notice.
- **DKIM missing blocks start when strict flag set:** `EMAIL_REQUIRE_FULL_DOMAIN_VERIFICATION=true` → 400.
- **Bounce suppression:** audience of 100 contacts, 3 have hard-bounce records → dispatch skips those, `Campaign.excluded_bounced_count=3`, `CampaignMessage` rows are only inserted for the remaining 97.

## Verification

Ajay's Workspace:

1. **Setup → Email Sender Setup**. Empty state — no verified domain.
2. Add domain `yourshop.com`. Modal shows three DNS records (SPF TXT, DKIM CNAME/TXT with selector `core-crm-{ajay-org-short-id}`, DMARC TXT). Copy them.
3. Add the records to DNS (or mock via a test DNS server for smoke). Click Verify → all three flip to ✓.
4. Add an address `product@yourshop.com` → verification email sent to that mailbox. Click the link → address `verified_at` set. Address now appears in the campaign create modal's mailbox picker.
5. Try to start an Email campaign using a disconnected mailbox → 400 with clear error banner.
6. Try to start with a verified mailbox on an unverified domain → warning banner on the campaign detail page but the campaign runs.
7. Set `EMAIL_REQUIRE_FULL_DOMAIN_VERIFICATION=true` in the org config → same campaign now blocks at start.
8. Send a campaign to a mixed audience including a known hard-bounce address. After start, the campaign detail page shows "N excluded (X hard-bounced, Y opted-out)". The bounced contact has no `CampaignMessage` row.
9. Delete a domain that's tied to a scheduled campaign → blocked with a clear reason.

## Self-check (fill in before the stop-and-report)

- 10 rules: line-by-line (esp. `org_id` filter on every domain + address query)
- Layered architecture: new module fully layered; only `service.py` commits; DNS lookup is a helper in `dns_check.py`
- Reuse: reused existing `EmailAccount`, `EmailBounce`, existing DKIM/SPF check helper if present, existing rate-limit middleware
- Query efficiency: bounce suppression is a single `IN(...)` query, not per-contact; domain verify runs three DNS lookups in parallel
- Compliance: SPF + DKIM + DMARC recommended for every domain; unverified sending is warn (not silent-block) to avoid trapping users behind DNS drift
- Security: DKIM private key stored encrypted (via existing SOPS integration or explicit column encryption); verification tokens are unguessable + rate-limited
- Tooling: prettier + eslint + ruff on all touched files; migrations verified up + down inside docker helper

## Awaiting your `proceed`

Done means: Sender Setup page renders + adds domains + shows DNS records + verifies them + adds addresses + verification email works + pre-flight blocks unverified starts + bounce suppression auto-excludes bounced contacts + Campaigns v1 ready for real customer sends. **Ship gate: Campaigns v1 done after 07b.**

If splitting per the recommendation above, the sub-steps land as `step-07a-email-sender-setup-backend.md` and `step-07b-email-sender-setup-frontend.md`. Rename in the README when the split is decided.
