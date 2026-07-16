# Step 06 — Email unsubscribe token + auto-appended footer + `email_opt_in_status` on Contact

**Goal:** Every Email campaign auto-appends an unsubscribe footer with a per-contact one-click token. Clicking the link flips `Contact.email_opt_in_status` to `opted_out` and the campaign engine excludes opted-out contacts from every future Email send. Non-negotiable for CAN-SPAM / GDPR / Gmail's one-click unsubscribe header.
**Track:** Campaigns page update — Email
**Status:** Pending
**Depends on:** Step 05 (Email actually sends; dispatch calls `adapter.send_email()`)

Screen references in [`preview.html`](preview.html):

- **Screen 4 · Create Campaign — Email** — the dashed footer strip under the composer: *"Auto-appended footer: Unsubscribe · Manage preferences · Sent by Your Shop, [postal address] — per-contact token, CAN-SPAM + GDPR compliant."*
- **Screen 6 · Contact — Email opt-out state** — the new "Email opt-in" pill next to the existing WhatsApp one.

---

## Scope

Backend adds three columns to `Contact` + a public unauthenticated unsubscribe endpoint + extends the email adapter's footer injector to embed the per-contact token URL + extends `send_guard.py` with an Email opt-in check. Frontend adds an "Email opt-in" badge on Contact detail + surfaces the auto-excluded count in the wizard.

**Explicitly NOT in this step:**

- Sender identity / mailbox picker (Step 03).
- HTML composer (Step 04).
- Bounce suppression pre-flight (Step 07 — belongs with sender-readiness).
- Sender Setup page UI (Step 07).

## Schema

Migration `00XX_contact_email_opt_in.py`:

| Column on `tbl_contacts` | Type | Constraint | Why |
|---|---|---|---|
| `email_opt_in_status` | ENUM(`never_contacted`, `opted_in`, `opted_out`) | NOT NULL DEFAULT `'never_contacted'` | Mirror of the existing `whatsapp_opt_in_status`. Explicit opt-in vs never-contacted matters for GDPR jurisdictions. |
| `email_opt_out_at` | TIMESTAMPTZ | nullable | When they clicked unsubscribe. |
| `email_opt_out_source` | TEXT | nullable | Free text — usually `"campaign:{campaign_id}"`. Also possible: `"manual"` for CRM-side toggles, `"bounce_hard"` for auto-suppression by the bounce classifier. |

Backfill existing rows to `'never_contacted'` (that's the default).

Migration `00XX_email_unsubscribe_tokens.py`:

New table `tbl_email_unsubscribe_tokens`:

| Column | Type | Constraint |
|---|---|---|
| `id` | UUID | PK |
| `org_id` | UUID | FK → `tbl_organizations.id`, NOT NULL |
| `contact_id` | UUID | FK → `tbl_contacts.id`, NOT NULL |
| `campaign_id` | UUID | FK → `tbl_campaigns.id`, nullable (transactional emails have no campaign) |
| `token` | TEXT | NOT NULL, UNIQUE, indexed |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT `now()` |
| `consumed_at` | TIMESTAMPTZ | nullable (set when the link is clicked) |

Token = URL-safe random 32-byte string (`secrets.token_urlsafe(32)`). Long enough to be unguessable; short enough to not overflow gateway URL length limits.

## Backend — public unsubscribe endpoint

New module surface. Not a new module — extend `campaigns/router.py` (or a small dedicated `unsubscribe_router.py` mounted at `/api/v1/unsubscribe`).

### `GET /api/v1/unsubscribe/{token}`

- Unauthenticated. Rate-limited by IP (existing rate-limit middleware).
- Look up `tbl_email_unsubscribe_tokens` by `token`. If not found → 404 HTML page ("Link expired or invalid").
- If found and `consumed_at` is null:
  - Load the contact, flip `email_opt_in_status='opted_out'`, set `email_opt_out_at=now()`, `email_opt_out_source='campaign:{campaign_id}'` (or `'transactional'` if no campaign).
  - Set the token's `consumed_at=now()`.
  - Audit-log the event (Reuse existing `audit_log.record()` — event type `contact.email_opted_out`).
- Return a clean HTML confirmation page ("You've been unsubscribed. Manage preferences → …"). Not a JSON response — the browser is loading it directly from an email link.

### `POST /api/v1/unsubscribe/{token}` (Gmail one-click)

- Same behaviour as GET but returns 200 empty. Gmail's `List-Unsubscribe-Post: List-Unsubscribe=One-Click` needs a POST-capable URL. Handler is the same DAL call.

### `GET /api/v1/unsubscribe/{token}/status`

- Optional — for the confirmation page's "Manage preferences" link if we ever add per-topic preferences. Return status only. Deferred until we need it.

## Backend — email adapter footer injection

Adapter already has footer injection at `send_email()` (see [`conversations/adapters/email.py`](../../api/src/app/core/conversations/adapters/email.py) around line 342). Extend it:

1. When `campaign_id` is passed, before injecting the footer:
   - Look up (or insert) a `tbl_email_unsubscribe_tokens` row for this contact + campaign. **Reuse if one exists** for the pair — cross-org matching is fine because tokens are unique per (contact_id, campaign_id).
   - Build the unsubscribe URL: `f"{BASE_URL}/api/v1/unsubscribe/{token}"`.
2. Inject into the HTML footer:
   ```
   <a href="{unsubscribe_url}">Unsubscribe</a> · Preferences · Sent by {org_name}, {postal_address}
   ```
3. Set the RFC-8058 headers on the outgoing email:
   - `List-Unsubscribe: <mailto:unsubscribe@{domain}?subject=Unsubscribe>, <{unsubscribe_url}>`
   - `List-Unsubscribe-Post: List-Unsubscribe=One-Click`

Postal address comes from `Organization.postal_address` (add column if missing; single migration line, doesn't need to be a separate step). Required by CAN-SPAM.

## Backend — `send_guard.py`

Extend `evaluate_contact` with an Email branch mirroring the WhatsApp opt-in logic:

- If `channel == email` and `contact.email_opt_in_status == 'opted_out'` → verdict `block`, reason `email_opted_out`. Applies to marketing AND transactional (DPDP/GDPR-consistent — opted out = opted out).
- If `never_contacted` and `campaign.category == 'marketing'` → verdict `warn` unless `allow_implicit=true` on the org config, else `block`.
- If `opted_in` → verdict `allow`.

Dispatch already calls `send_guard.evaluate_contact` around line 636–655 of `campaigns/service.py`; no change to the caller.

## Backend — bulk unsub for contact-side actions

Reuse-first: Contact detail page probably has an existing "manual actions" menu (edit, delete, tag) — add an "Unsubscribe from Email" toggle that flips `email_opt_in_status` on the row directly, without a token. Written by a user with permission `contact.edit`. Records audit event `contact.email_opted_out` with `source='manual'`.

## Frontend — Contact detail badge

`app/src/app/features/user/core/contacts/contact-detail/` — extend the header pill row where WhatsApp opt-in status already renders. Add an "Email opt-in" pill using the same visual pattern (green `Opted in`, red `Opted out`, gray `Never contacted`).

On hover / detail card, if opted out show timestamp + source ("Unsubscribed 2026-07-14 via campaign 'June newsletter'").

## Frontend — Wizard exclusions surfacing

Campaign wizard already shows an "Exclusions" section (see Step 03's design). Add two auto-applied lines when channel = Email:

- "Skip contacts who unsubscribed from Email" — always-on, checkbox disabled with a lock icon.
- Live count: "N contacts will be excluded" — computed from `audience_filter` intersected with `email_opt_in_status='opted_out'` at wizard step 2.

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/00XX_contact_email_opt_in.py` | created |
| `api/alembic/versions/00XX_email_unsubscribe_tokens.py` | created |
| `api/alembic/versions/00XX_organization_postal_address.py` | created (if column missing) |
| `api/src/app/core/contacts/models.py` | modified — three new columns |
| `api/src/app/core/campaigns/models.py` | modified — `EmailUnsubscribeToken` ORM class |
| `api/src/app/core/campaigns/schemas.py` | modified — schemas for public unsubscribe endpoint responses |
| `api/src/app/core/campaigns/service.py` | modified — token creation on dispatch; `opt_out_contact_for_campaign()` |
| `api/src/app/core/campaigns/data_access.py` | modified — token CRUD helpers |
| `api/src/app/core/campaigns/router.py` | modified — public `GET/POST /unsubscribe/{token}` endpoints |
| `api/src/app/core/campaigns/send_guard.py` | modified — Email branch |
| `api/src/app/core/conversations/adapters/email.py` | modified — token URL injection + List-Unsubscribe headers |
| `api/src/app/core/tenants/models.py` | modified — `Organization.postal_address` (if missing) |
| `api/tests/test_email_unsubscribe.py` | created |
| `app/src/app/features/user/core/contacts/contact-detail/*` | modified — Email opt-in badge + manual toggle |
| `app/src/app/features/user/core/campaigns/create-campaign-modal.component.{ts,html}` | modified — auto-applied exclusion row |

**~11 files + 2–3 migrations.** At the edge of the per-step rule. If line count creeps past ~400, split into **06a** (schema + tokens + endpoint + adapter) and **06b** (send_guard + contact badge + wizard exclusions).

## Tests

`test_email_unsubscribe.py`:

- **Token creation:** dispatch triggers a token row per (contact_id, campaign_id). Re-dispatching the same campaign uses the same token.
- **Public GET flow:** hit `/api/v1/unsubscribe/{token}` → 200 HTML, contact row's `email_opt_in_status='opted_out'`, `email_opt_out_at` set, `email_opt_out_source='campaign:{id}'`. Second call → 200 HTML (idempotent) but no double-write.
- **Public POST flow (Gmail one-click):** same behaviour, returns 200 empty body.
- **Bad token:** 404 with friendly page. Rate-limit trips after N tries per IP.
- **Send guard blocks opted-out:** dispatch to a contact with `email_opt_in_status='opted_out'` → row marked failed with reason `email_opted_out`.
- **Manual toggle:** authenticated PATCH on contact flipping `email_opt_in_status` records `source='manual'` in audit log.
- **Cross-org tokens:** token from Org A cannot flip a contact belonging to Org B — 404 by design (query filters by `org_id`).

## Verification

Ajay's Workspace:

1. Prereq — Step 05 landed, Email campaigns can send.
2. Set `Organization.postal_address` on Ajay's org (via SQL or the settings page if it exists).
3. Send an Email campaign to yourself. Open the received email.
4. Confirm the footer is present with an Unsubscribe link and Manage preferences link. Click Unsubscribe.
5. Browser lands on the confirmation page. Your contact in the CRM now shows an "Email opt-in: Opted out" badge with timestamp + source.
6. Try sending another Email campaign that includes yourself in the audience — the wizard's exclusion row shows "1 contact excluded (email opted-out)". After dispatch, verify your row is failed with reason `email_opted_out`.
7. Try opening a bad token URL (`/api/v1/unsubscribe/deadbeef`) → 404 confirmation page.
8. Check Gmail's inbox → the message shows Gmail's own one-click Unsubscribe button in the top bar (proves `List-Unsubscribe` headers are set). Click it → row flips to opted-out.
9. Contact detail — click the manual "Unsubscribe from Email" toggle on a different contact → row flips, audit log shows `source='manual'`.

## Self-check (fill in before the stop-and-report)

- 10 rules: line-by-line (esp. `org_id` filter on token lookup + contact update)
- Layered architecture: public router → service → DAL; only service commits; token generation is a pure utility
- Reuse: existing footer injector, existing audit-log recorder, existing rate-limit middleware, existing `send_guard` shape
- Query efficiency: token lookup uses UNIQUE index; token creation is one INSERT per (contact, campaign) — reused on re-dispatch
- Security: token unguessable (32-byte urlsafe); rate-limited; no PII in the URL
- Compliance: List-Unsubscribe (RFC 8058) + List-Unsubscribe-Post + human-readable footer + postal address = CAN-SPAM + GDPR + Gmail-compliant
- Tooling: prettier + eslint + ruff on all touched files; migrations verified up + down inside docker helper

## Awaiting your `proceed`

Done means: unsubscribe links work end-to-end, opted-out contacts stay out of future sends, Gmail one-click surfaces, manual toggle works, audit log records source, spec + pytest suites green, browser smoke green.
