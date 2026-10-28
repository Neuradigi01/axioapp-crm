# Step 3.5.6 — Campaign dispatch: text-vs-template branch + per-contact variable substitution

**Goal:** `dispatch_chunk` knows the difference between a free-text campaign and a template campaign. For template campaigns, resolves the variable bindings against each contact and calls `adapter.send_template(...)` instead of `adapter.send(...)`.

**Phase:** 3.5
**Depends on:** 3.5.5 (adapter `send_template`, campaign `template_id` + `template_variables`)
**Status:** ✅ COMPLETED — code wired; tests pending Docker restart for run-verify

After this step a real template campaign delivers — the Celery task (currently in-process per dev default) walks the contact list, substitutes `{{1}}=contact.full_name`, `{{2}}=campaign.template_variables['2']` etc., and POSTs each to Meta.

---

## Scope

### In-scope

- Helper `_resolve_template_variables(campaign, contact) -> dict[int, str]`:
  - Reads `campaign.template_variables` (set by the picker in 3.5.5 — shape `{"1": {"kind":"static","value":"30%"}, "2": {"kind":"field","value":"contact.full_name"}}`).
  - Resolves `"kind=field"` against the contact (full_name, phone, email, custom_data.<key>).
  - Resolves `"kind=static"` verbatim.
  - Returns a flat `{1: "Asha", 2: "30%"}` dict.
  - Raises `TemplateVariableUnresolvable` if a required variable can't be filled (e.g. contact has no full_name).
- Update `dispatch_chunk`:
  - Load `whatsapp_templates` row when `campaign.template_id is not None` (one query before the loop, cached for the chunk).
  - Per-contact: resolve variables → call `adapter.send_template(template=row, variables=resolved)`.
  - On `TemplateVariableUnresolvable` → mark `CampaignMessage.failed` with reason; continue.
- New test cases:
  - Template campaign happy path → message uses `send_template`, variables resolved correctly.
  - Contact missing required field → message marked failed, others continue.
  - Mixed-channel sanity: non-WA campaign still uses `send` (text).

### Out-of-scope

- New custom-field types in variable resolution → covered if `custom_data` JSON read works; advanced (e.g. computed fields) deferred.
- Conditional templates (different templates per segment) → P2.

---

## Files to touch

### Modified (3)
- `API/src/app/core/campaigns/service.py` — extend `dispatch_chunk`, add helper
- `API/src/app/core/campaigns/models.py` — N/A (columns added in 3.5.5)
- `API/tests/test_campaigns_template_send.py` (new) — 3-4 cases

**File budget:** 3 files.

---

## Plan

1. **Helper:** Pure function — takes campaign + contact, returns int→str dict. Easy to unit-test in isolation.
2. **Dispatch loop:** Branch on `campaign.template_id is None` — text path is existing, template path uses new method.
3. **Error mapping:** `TemplateVariableUnresolvable` and `WhatsAppSendError` both flow into `CampaignMessage.failed` with distinct error messages.
4. **Tests:** Use the existing `_CapturingSession` pattern + mocked Meta HTTP.

---

## Pre-implementation question

**Q:** Agar template ke `{{1}}` ke liye contact field hai `contact.full_name` aur woh empty hai — message FAIL kar dein ya **fallback** mein contact.phone use kar dein?

- **(a) Fail per message.** Strict — operator dekhega aur fix karega contact data.
- **(b) Fallback chain** — full_name → phone → email → "Customer" (generic). Lenient, fewer failed sends.

**Recommendation: (b)** — bulk campaigns mein 1-2% empty fields normal hai. Strict fail rate hurts conversion. Fallback chain documented per template variable.

---

## Verification + Self-check + Stop & report — standard
