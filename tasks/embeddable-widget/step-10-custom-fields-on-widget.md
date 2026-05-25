# Step 10 — Widget: opt-in custom fields on the form

**Goal:** Let the Owner expose contact-level custom fields on the embeddable widget so visitors can fill them in directly (instead of staff filling them in afterwards via the edit form). Opt-in per field — the Owner picks which custom fields appear, defaulting to none, so internal-only fields like `internal_notes` can't leak to website visitors.
**Track:** Embeddable Widget
**Status:** Done — `WidgetConfigField` now carries a `field_source: "standard" | "custom"` discriminator and `key` is a free-form string when `field_source='custom'`; a `model_validator` rejects mismatches (standard-source key must be in the 5 baked-in field keys). `EmbedSubmission` gets a `custom_data: dict[str, Any] = {}` payload field. The submission service's `_validate_payload_against_config` was extended to also gate `custom_data.*` keys against the org's configured custom fields (rule 1b) and enforce required + select-options rules against custom fields too. `submissions.submit` routes `payload.custom_data` (minus empties) into `ContactCreate.custom_data` on first-contact creation; dedup'd repeat visitors don't get their `custom_data` overwritten (intentional — Owner controls existing contacts via the edit form). `config_service.update` runs `_validate_custom_field_refs(session, fields)` after schema validation: every custom-source field must reference a row in `custom_field_definitions` with `entity_type='contact'` AND a `field_type` in `_WIDGET_SUPPORTED_CUSTOM_TYPES = {text, number, select, date, phone, email}` (multiselect/datetime/boolean/currency rejected with a clear "not supported on widget" error). New `GET /api/v1/embed/available-custom-fields` admin endpoint returns `list[AvailableCustomField]` with a `widget_supported` flag so the Settings picker can grey out unsupported types. Widget side: `types.ts` extends `WidgetFieldType` with `number` and `date`, splits `WidgetStandardFieldKey` from a general `key: string`, adds `field_source` to `WidgetField`, adds `custom_data?: Record<string, string>` to `SubmissionPayload`. `renderer.ts` updates the submit handler to iterate fields once and route values into either the standard payload slots or `custom_data[key]` based on `field.field_source`; `htmlInputType` handles `number` and `date`. `FALLBACK_CONFIG` updated with `field_source: "standard"` on every default field so the offline-fallback shape stays type-valid. Settings UI: `embed-api.service.ts` types `WidgetFieldSource`, `AvailableCustomField`, and adds `listAvailableCustomFields()`; component adds `availableCustomFields` signal (lazy-loaded on first picker open), `pickerOptions` computed signal (filters out already-added fields), `openPicker/closePicker/addCustomField/removeField` handlers; template adds a `CUSTOM` badge next to custom-source field rows, a Trash2 remove button per row, and an "Add custom field to widget" picker with per-field Add buttons that disable when `widget_supported=false`. Existing widget config rows missing `field_source` get `"standard"` defaulted by Pydantic on read — no migration needed. Tests: `test_embed_spam.py` adds 2 new specs (`test_custom_field_value_routes_into_contact_custom_data` verifies a widget-submitted `address` value lands in the created contact's `custom_data`; `test_unconfigured_custom_field_rejected_422` verifies a forged `internal_notes` key gets 422'd because it's not in the org's widget config). 36/36 backend tests green (24 spam + 2 new + 10 submission-log) + 16/16 widget tests green + Angular dev build clean. Widget bundle now **15.44 KB raw / 4.88 KB gzipped** (was 4.74 KB; +0.14 KB for the routing branch, well under 30 KB ceiling).
**Depends on:** Step 9 (submission log relies on the same routing pipeline), `core/custom_fields` module (read-only — pulls contact custom-field defs).

---

## Scope

In-scope:

- **Backend schema:** add `field_source: "standard" | "custom"` to `WidgetConfigField`; relax `key` from a fixed Literal to a free string when source=custom (validated by `model_validator`). Add `number` + `date` to `WidgetFieldType` for common custom-field shapes (budget, preferred-delivery-date). Add `custom_data: dict` to `EmbedSubmission`.
- **Backend validation:** `_validate_payload_against_config` enforces three rules across both standard and custom fields:
  1. Every supplied value must reference a configured field.
  2. Required fields (any source) must be non-empty.
  3. Select fields' values must be in the configured `options`.
- **Backend submission routing:** `payload.custom_data` (with empty values dropped) lands in `ContactCreate.custom_data` on contact creation. Dedup'd existing contacts keep their existing custom data — widget-submitted values don't overwrite staff-curated ones.
- **Backend config validation:** PUT `/embed/config` validates that every custom-source field references a row in `custom_field_definitions` for `entity_type='contact'` AND has a `field_type` the widget renderer supports.
- **Backend endpoint:** new `GET /embed/available-custom-fields` returns the contact custom fields available to opt in, with a `widget_supported` flag.
- **Widget bundle:** renderer routes values into `custom_data` for custom-source fields, handles `number`/`date` input types. ~0.14 KB gzipped growth.
- **Settings UI:** new "Add custom field to widget" picker (inline, lazy-loaded list of available custom fields) + Trash2 Remove button on every field row (standard or custom). Custom-source rows get a "CUSTOM" badge so the Owner can tell them apart.
- **Tests:** 2 new pytest cases covering custom-field routing happy path + forged-field 422.

Out of scope:

- **Lead-entity custom fields on the widget** — v1 supports contact-entity custom fields only. The widget creates a contact + a lead together; lead-entity custom fields can be added in a future step if Owners want them on the visitor surface.
- **File / image custom fields** — separate larger surface (file upload + storage).
- **Multiselect / datetime / boolean / currency custom-field types** — unsupported types stay in the picker list (so the Owner sees the field exists) but the Add button is disabled with a `widget_supported=false` indicator.
- **Bulk-edit "expose all my custom fields"** — opt-in per field by design (safer; one accidental click can't leak sensitive fields). Can add a convenience "show all" toggle later if Owners ask.

## Files touched

| File | Action |
|---|---|
| `api/src/app/core/embed/schemas.py` | modified — `field_source`, `custom_data`, `AvailableCustomField`, expanded `WidgetFieldType` |
| `api/src/app/core/embed/submissions.py` | modified — validation rules 1b/2/3 extended for custom fields, `payload.custom_data` → `ContactCreate.custom_data` |
| `api/src/app/core/embed/config_service.py` | modified — `_validate_custom_field_refs`, `list_available_contact_custom_fields`, `_WIDGET_SUPPORTED_CUSTOM_TYPES` |
| `api/src/app/core/embed/router.py` | modified — new `GET /embed/available-custom-fields` endpoint |
| `api/tests/test_embed_spam.py` | modified — 2 new `TestCustomFieldRouting` specs |
| `widget/src/types.ts` | modified — `WidgetFieldSource`, expanded `WidgetFieldType`, free-form `key`, `custom_data` on payload |
| `widget/src/renderer.ts` | modified — route values into `custom_data`, handle `number`/`date` input types |
| `widget/src/index.ts` | modified — `FALLBACK_CONFIG` adds `field_source: "standard"` to every default field |
| `widget/test/renderer.test.ts` | modified — `makeConfig` fields carry `field_source: "standard"` |
| `app/src/app/features/user/core/settings/tabs/embed-api.service.ts` | modified — `WidgetFieldSource`, `AvailableCustomField`, `listAvailableCustomFields()` |
| `app/src/app/features/user/core/settings/tabs/embed-integrations-tab.component.ts` | modified — picker signals, `openPicker`/`addCustomField`/`removeField` handlers |
| `app/src/app/features/user/core/settings/tabs/embed-integrations-tab.component.html` | modified — Trash2 remove button per row, CUSTOM badge, inline picker UI |

**12 files.** Cohesive; splitting into 10a (backend) + 10b (frontend) would scatter the changes unnecessarily.

## How to verify (manual smoke)

1. **Define a contact custom field** under Settings → Custom fields if you haven't already (e.g. `address`, type=text, required=true).
2. **Open** Settings → Integrations → Embed widget → "Keys & configuration" tab.
3. **Click "Add custom field to widget"** — picker opens, your `address` field appears with an "Add" button.
4. **Click Add** → `address` row appears in the fields table with a `CUSTOM` badge.
5. **Click "Save configuration"** → green "Saved." indicator.
6. **Reload** the widget test page (`http://localhost:5173/dev/test-host.html?key=…`) — the form now includes the Address field below the standard ones.
7. **Submit the form** with values in Name, Phone, AND Address → green ✓ thank-you state.
8. **Open the new lead** in `/user/leads` → click into the contact → custom fields panel shows Address populated with the value the visitor typed.
9. **Forged-payload check** (DevTools Console):
   ```js
   fetch("http://localhost:8000/api/v1/embed/leads", {
     method: "POST",
     headers: {"Content-Type":"application/json","X-FurniCRM-Key":"pk_live_…"},
     body: JSON.stringify({full_name:"Bot",phone:"+919000000000",
       rendered_at:new Date(Date.now()-10000).toISOString(),
       custom_data:{internal_notes:"forged"},
       attribution:{referrer:null,landing_url:null,utm_source:null,utm_medium:null,utm_campaign:null,utm_content:null,utm_term:null}})
   }).then(r => console.log(r.status, r.json()))
   ```
   → Expect `422` because `internal_notes` isn't in the widget config.

## Acceptance criteria

- Owner can add any supported contact custom field to the widget via a single click in Settings.
- Owner can remove any field (standard or custom) from the widget — reversible by re-adding.
- Visitor's widget submission with values in the opted-in custom fields lands in the contact's `custom_data` JSONB.
- Forged submissions targeting unconfigured custom fields are rejected 422 (can't bypass the opt-in gate).
- Existing widget configs (without `field_source` on fields) read cleanly — Pydantic defaults to `"standard"`.

## Risks + trade-offs

- **Dedup overwrites:** when a visitor with a phone match to an existing contact submits, we DON'T overwrite their `custom_data` — the existing values stay. Pro: staff-curated data is sacrosanct. Con: a visitor's correction to their address never reaches the contact. Acceptable for v1; if Owners complain, add a per-org toggle.
- **Custom-field type drift:** if Owner adds a `multiselect` field to contact, then later renames it to `select` in Settings → Custom fields, the existing widget config still passes validation (the type check runs on the current def). Acceptable — Settings → Custom fields owns the schema, widget config follows.
- **Picker doesn't auto-refresh:** if the Owner opens Settings → Embed → opens the picker (loads list) → in another tab adds a new custom field → comes back to the picker, the new field doesn't appear until they reload. Trade-off accepted for v1; can add a refresh button later.
- **Required custom field on widget = required for submit:** if the Owner marks a custom field `required=true` AND adds it to the widget, visitors MUST fill it in (existing validation rule 2 catches this and the renderer's client-side check marks the field invalid). Aligns with how `required` already works for standard fields.

## Rollback

Revert the listed files + delete `step-10-custom-fields-on-widget.md`. Existing JSONB widget configs would still validate (the `field_source` field defaults to `"standard"` which is the pre-change behaviour); no DB rollback needed.
