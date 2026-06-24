# Step 11 — Campaigns refactor (generic template_id)

**Goal:** Switch `tbl_campaigns.template_id` FK target from `tbl_whatsapp_templates` to `tbl_message_templates`. Campaign dispatch renders through the per-channel adapter using the generic template. Campaign create modal picks templates from the central library filtered by chosen channel.
**Status:** Pending
**Depends on:** Step 9 (WA migration — every WA template now has a central row), Step 10 (Email migration — same). Step 11 should NOT precede them.

---

## Scope

In-scope:
- Migration `<ts>_campaigns_template_fk.py`:
  - For every `tbl_campaigns` row with `template_id IS NOT NULL`: remap the FK value from the WA template UUID to the matching central `tbl_message_templates.id` (lookup via `tbl_whatsapp_templates.message_template_id` from Step 9).
  - Drop the old FK constraint targeting `tbl_whatsapp_templates`; add a new FK constraint targeting `tbl_message_templates(id) ON DELETE SET NULL` (matches current behavior).
  - Reversible: down restores the original FK target by reverse-remapping.
- `core/campaigns/models.py`: update the relationship target on `Campaign.template`.
- `core/campaigns/service.py`:
  - `create_campaign` accepts a generic `template_id` regardless of channel.
  - `dispatch_chunk` resolves `template.channel` from the central row, picks the channel adapter, and renders via that adapter using the template body + variables resolved per recipient.
  - Removes the WA-specific template loading branch (in `service.py` line 492+); replaces with generic load.
- `core/campaigns/schemas.py`: `CampaignCreate.template_id` field doc updated; channel validator confirms the chosen template's channel matches the campaign's channel.
- Frontend `APP/.../core/campaigns/create-campaign-modal.component.{ts,html}`:
  - Template picker now hits `GET /api/v1/templates?channel={selected_channel}&internal_status=published`.
  - Picker shows template name + variable preview chips.
  - Removes the existing WA-specific template loading path.
- `APP/.../core/campaigns/campaigns-api.service.ts`: drop the WA-specific template list call.

Out of scope:
- Email campaigns (channel=email) sending — already works via the email channel adapter; this step just makes the FK swap work for them too. Email campaigns become viable end-to-end here.
- Step 21 (A/B testing) cross-track impact — A/B campaigns reference two templates; both must be central. Step 21's `variant_a_template_id` / `variant_b_template_id` FKs remap in this same migration so future A/B campaigns keep working.

## Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/<ts>_campaigns_template_fk.py` | **NEW** |
| `API/src/app/core/campaigns/models.py` | edit — relationship target |
| `API/src/app/core/campaigns/service.py` | edit — channel-generic template load + dispatch via adapter |
| `API/src/app/core/campaigns/schemas.py` | edit — channel-matches-template validator |
| `APP/src/app/features/user/core/campaigns/create-campaign-modal.component.ts` | edit — template picker |
| `APP/src/app/features/user/core/campaigns/create-campaign-modal.component.html` | edit — template picker |
| `APP/src/app/features/user/core/campaigns/campaigns-api.service.ts` | edit — drop WA-specific call |
| `API/tests/campaigns/test_template_resolver.py` | **NEW** |

**~8 files. ~450 lines.**

## Plan

1. Migration — careful: A/B campaigns have THREE template FKs (`template_id`, `variant_a_template_id`, `variant_b_template_id`). All three remap.
2. `service.py`: generic load + channel-based adapter resolution. Reuse the existing `resolve_channel(...)` from `core/conversations/registry.py`.
3. Dispatch: render via adapter, send via adapter, persist `campaign_message.channel_message_id`.
4. Schema validator: a campaign with `channel=email` requires `template.channel=email` (server-side cross-check).
5. Frontend: picker is filtered list of published templates of the chosen channel.
6. Tests: campaign with WA template dispatches; campaign with Email template dispatches; mismatched channel rejected.

## DB changes / migrations

One migration remapping three FK columns on `tbl_campaigns`. Reversible.

## Tests

7 pytest cases:
- `test_campaign_with_wa_template_loads_correctly`
- `test_campaign_with_email_template_loads_correctly`
- `test_campaign_channel_mismatch_rejected_on_create`
- `test_dispatch_chunk_routes_through_channel_adapter`
- `test_dispatch_chunk_renders_variables_per_recipient`
- `test_ab_variant_templates_remapped_correctly` (Step 21 compatibility)
- `test_archived_template_blocks_campaign_start`

## Smoke

```
1. Pre-migration: SELECT template_id FROM tbl_campaigns LIMIT 5 — note original UUIDs.
2. Run migration.
3. SELECT template_id FROM tbl_campaigns WHERE template_id IS NOT NULL → all values now resolve to tbl_message_templates rows.
4. /user/campaigns/new — pick channel=Email, template picker shows email templates.
5. Launch a small campaign → email sends; campaign_message.status flips to sent.
6. /user/campaigns/new — pick channel=WhatsApp, template picker shows WA templates.
7. Launch a small WA campaign → message sends.
```

## Risks

- Mid-flight campaigns (already running) — migration must not stop in-flight Celery jobs. Migrate the FK constraint without touching active rows' message dispatch (existing in-memory campaign refs hold their `template_id` UUID, which is now a central row's UUID; both schemas reference the same UUID space because the central row was created with `template_id = old_wa_template.message_template_id`).
- Existing analytics joins in `core/reporting/campaign_analytics.py` that join `tbl_campaigns → tbl_whatsapp_templates` need updating to join through `tbl_message_templates` instead. Audit + update in this step.

## Self-check (10 rules)

`core/campaigns/`. ✓ org_id preserved. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions unchanged. pack.yaml untouched. ✓ 8 files / ~450 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 11 — Campaigns refactor (generic template_id)
Files: 8
Verify: campaigns with WA templates still send; new email campaigns send; A/B variant templates remapped; channel mismatch rejected.
Tests: 7 pytest cases.
Awaiting "proceed".
```
