# Step 7: Frontend — Sending Domains tab + DNS records renderer + Claim modal

**Status:** Pending

## Goal

Owner-facing UI for the domain flow. Renders Mailgun's verbatim records, shows state, exposes claim / verify / release actions.

## Files touched

- `APP/src/app/features/user/core/settings/email/sending-domains-tab.component.ts` (+ html + scss)
- `APP/src/app/features/user/core/shared/dns/dns-record-card.component.ts` (+ html + scss)
- `APP/src/app/features/user/core/settings/email/claim-domain-modal.component.ts` (+ html + scss)
- `APP/src/app/features/user/core/settings/email/sending-domains.service.ts`
- `APP/src/app/features/user/core/settings/email/models.ts` — types
- `APP/src/app/features/user/core/settings/tabs/email-settings-tab.component.ts` — register new tab

## What this step does

- New standalone component `sending-domains-tab`:
  - Header: "Sending domains" title, "Claim domain" button.
  - Empty state: "No sending domains claimed. All mail sends from the shared platform address. [Claim your domain]".
  - List: cards per domain. Card shows: domain string, status badge (color-coded per state), `Last verified: <relative>`, region flag, 3 actions in overflow menu (Check now, Release).
  - Expandable "DNS records" section: renders `<app-dns-record-card>` per entry in `dns_records`.
- `<app-dns-record-card>` (shared under `features/user/core/shared/dns/`):
  - Inputs: `record: {record_type, name, value, priority?}`.
  - Layout: two rows (Host + Value), each with copy-to-clipboard button. Priority column shows only for MX.
  - Matches existing embed-integrations copy pattern.
- Claim modal:
  - Input: domain (with live RFC 1035 label validation).
  - Region dropdown: US / EU.
  - Submit → POST → success shows records inline immediately.
- State-based badges + banners:
  - `verified` → green badge.
  - `pending` → grey badge with countdown "Next check in Xh".
  - `demoted` → amber standard warning banner: "Records drifted. Fix at your DNS provider to restore delivery."
  - `released` → grey with strikethrough.
- Service:
  - `list()` → `GET /api/v1/sender-domains`
  - `claim({domain, region})` → `POST /api/v1/sender-domains`
  - `verify(id)` → `POST /api/v1/sender-domains/{id}/verify`
  - `release(id)` → `DELETE /api/v1/sender-domains/{id}`
  - HTTP retry interceptor applies for GET (per memory `feedback_http_retry_interceptor.md`).

## Tests (Karma)

- `test_domains_tab_renders_dns_records_from_jsonb_verbatim`
- `test_domains_tab_check_now_button_triggers_verify_and_refreshes_row`
- `test_domains_tab_demoted_domain_shows_amber_warning_banner`
- `test_dns_record_card_copy_button_copies_value_exact`
- `test_dns_record_card_shows_priority_column_only_for_mx`
- `test_claim_modal_validates_domain_inline`
- `test_claim_modal_rejects_scheme_urls_pre_submit`
- `test_empty_state_shows_claim_cta`

## Verification checklist

- [ ] Karma tests pass
- [ ] Prettier applied (memory `feedback_prettier_on_write.md`)
- [ ] Lucide icons registered (memory `feedback_lucide_icon_registry.md`)
- [ ] Manual smoke in browser at Ajay's Workspace (`41f9ede9-41b3-44ce-b489-3004566d4068`): claim → records display → verify (fails until DNS added) → wait → verify succeeds → demoted state after 3 fake failures → release
- [ ] `ng build` clean

## Self-check

- Rule 4 (permissions): pass — server enforces Owner-only.
- Reuse: pass — dns-record-card is shared for future custom-inbound-domain tab.
- Memory `feedback_reusable_code_lives_in_shared.md`: pass.
- Memory `feedback_standard_warning_banner_pattern.md`: pass.
- Memory `feedback_branding_crm_not_furnicrm.md`: pass — uses "CRM" not "FurniCRM".

## Stop-and-report

Report Karma pass, browser smoke output, screenshots (verified state, demoted state). **Track 2 done. Awaiting your "proceed" for Track 3 step 1.**
