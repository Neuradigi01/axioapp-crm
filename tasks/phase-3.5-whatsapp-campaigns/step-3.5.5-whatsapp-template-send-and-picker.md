# Step 3.5.5 — Template send: adapter method + campaign template picker + Settings "Sync" button

**Goal:** End-to-end template-message capability — the WhatsApp adapter gains a `send_template(...)` method, the Settings UI gets a "Sync templates" button (visible when connected), and the campaign create-modal gains a template picker with variable inputs.

**Phase:** 3.5
**Depends on:** 3.5.4 (`whatsapp_templates` table + sync API)
**Status:** ✅ COMPLETED — backend tests 30/30 + Angular build clean

After this step a campaign author can: open Create Campaign → pick channel "WhatsApp" → pick from approved templates → fill in `{{1}} = full_name`, `{{2}} = "sofa set"` style variable bindings → save as draft. Actual dispatch happens in Step 3.5.6.

---

## Scope

### In-scope

**Backend:**
- New `WhatsAppAdapter.send_template(...)` method on the existing adapter — builds Meta's `type=template` envelope:
  ```json
  {"messaging_product":"whatsapp","to":"…","type":"template",
   "template":{"name":"diwali_sale","language":{"code":"en_US"},
   "components":[{"type":"body","parameters":[{"type":"text","text":"Asha"}]}]}}
  ```
- Helper `_render_template_components(template_row, variable_bindings)` that turns a `WhatsAppTemplate` row + a `{"1":"Asha","2":"sofa"}` dict into Meta's `components` array (handles BODY parameters; HEADER text params if `header_type='TEXT'`).
- Extend `Campaign` model + schema with optional `template_id` (FK → `whatsapp_templates.id`) and `template_variables` (JSONB) for template campaigns. The existing `template` text column stays for non-WA channels.
- Migration `0063_campaigns_template_id.py` — add the two columns + FK + INDEX.

**Frontend:**
- Settings → Integrations → WhatsApp card gets a "Sync templates" button (visible only when `status==='connected'`). Click → POST `/templates/sync` → toast with `{added, updated, removed}` counts.
- Campaign Create Modal: when channel is WhatsApp, swap the free-text "Template" textarea for a 2-pane picker:
  - Left pane: dropdown filtered by `status=APPROVED`, grouped by `category` (Marketing / Utility / Authentication).
  - Right pane: live preview of selected template's body + per-variable text inputs (one for each `{{n}}`).
  - Submit serializes `template_id` + `template_variables` into the campaign payload.

### Out-of-scope

- Dispatch branching (text vs template at send time) → Step 3.5.6.
- Per-contact variable mapping from contact fields (e.g. `{{1}} = contact.full_name` auto-substitution) → Step 3.5.6 design.
- Image/Video/Document header parameters → P2 (text headers only in this step).

---

## Files to touch

### Created (1)
- `API/alembic/versions/0063_campaigns_template_id.py`

### Modified (~7)
- `API/src/app/core/conversations/adapters/whatsapp.py` — add `send_template`
- `API/src/app/core/campaigns/models.py` — add `template_id`, `template_variables`
- `API/src/app/core/campaigns/schemas.py` — extend `CampaignCreate` / `CampaignUpdate` / `CampaignRead`
- `API/tests/test_whatsapp_template_send.py` (new) — adapter unit tests
- `APP/src/app/features/user/core/settings/integrations/whatsapp-card.component.{ts,html}` — "Sync" button
- `APP/src/app/features/user/core/campaigns/campaign-create-modal.component.{ts,html}` (or equivalent) — picker

**File budget:** ~10 files. Borderline; if `campaign-create-modal` is large, split picker into its own component → split into a 3.5.5a/3.5.5b within this step's scope.

---

## Plan

1. **Migration `0063`:** add columns to `campaigns`; column `template_id` is nullable (text channels don't use it), FK with ON DELETE SET NULL (preserves campaign history if template is deleted from Meta — see Step 3.5.4 trade-off).
2. **Adapter `send_template`:** signature `send_template(*, org_id, external_id, template, variables) -> ChannelMessageRef`. POSTs to same `/messages` endpoint with `type=template`. Maps Meta error codes to our existing `WhatsAppSendError`.
3. **Campaign schema:** `template_id` + `template_variables` are mutually-exclusive with the free-text `template` column for WA channel — backend validates "either text or template, not both" for WhatsApp channel.
4. **Frontend "Sync" button:** existing card gets a small secondary button next to "Test connection". POSTs to sync endpoint, shows toast.
5. **Frontend picker:** Reactive form group with `templateId` + `variables: FormRecord<string>`. On template selection, the form dynamically rebuilds `variables` controls based on the template's `variable_count`.
6. **Tests:** adapter send_template happy path + Meta error path (101 — recipient not on WhatsApp).

---

## Pre-implementation question

**Q:** Variable bindings UI mein — operator har campaign mein har variable manually type kare ya **contact field mapping** offer karen (`{{1}}` ko dropdown `contact.full_name` se bind karne ka option)?

- **(a) Manual type only** — simpler UI, but operator types same value for every contact (template wouldn't personalise per recipient)
- **(b) Field mapping dropdown** — variable inputs dual-mode: "Static text" OR "Contact field" (full_name, phone, email, custom field). Per-contact personalisation. ~30% more frontend code.

**Recommendation: (b)** — without field mapping, template messages lose their personalization advantage. This is the whole point of WhatsApp templates (vs free text).

---

## Verification + Self-check + Stop & report — standard template (same shape as 3.5.4)
