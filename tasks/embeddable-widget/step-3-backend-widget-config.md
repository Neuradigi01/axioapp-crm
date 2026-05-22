# Step 3 — Backend: per-org widget config (visible fields, thank-you URL, branding)

**Goal:** Give each org a single, editable widget config that controls which fields appear in their embedded form, the labels/placeholders/required state per field, the post-submit thank-you URL, and high-level branding hints (logo URL, accent colour). The public `GET /api/v1/embed/config?key=…` endpoint serves this config to the widget at render time.
**Track:** Embeddable Widget
**Status:** Pending
**Depends on:** Step 1 (`embed_keys` for the key → org lookup), Step 2 (submission endpoint), Standard Field Overrides track (the field registry — widget reuses the existing `core/standard_fields/` registry to enumerate available fields).

---

## Scope

In-scope:

- Alembic migration adding `widget_configs` table — one row per org, lazily created on first read or first key issuance.
- SQLAlchemy `WidgetConfig` model + Pydantic schemas.
- `core/embed/config_service.py`:
  - `get_or_create(org_id) -> WidgetConfig` — returns the org's config, creating defaults on first call.
  - `update(org_id, actor, payload)` — patch-style update.
- Admin endpoints:
  - `GET /api/v1/embed/config` — returns current config (admin auth, permission `settings.integrations.embed.manage`).
  - `PUT /api/v1/embed/config` — update (same permission).
- Public endpoint:
  - `GET /api/v1/embed/config/public?key=pk_live_…` — returns the rendering shape the widget needs (no admin-only metadata). Resolves key → org via `embed.service.find_by_plain_key`. CORS open. Cached client-side (and via Cache-Control) for ~60s.
- Default config shape on first create:
  ```json
  {
    "fields": [
      {"key": "full_name", "label": "Your name", "placeholder": "Asha Reddy", "required": true,  "order": 0},
      {"key": "phone",     "label": "Phone",     "placeholder": "+91 …",       "required": true,  "order": 1},
      {"key": "email",     "label": "Email",     "placeholder": "you@…",       "required": false, "order": 2},
      {"key": "interest",  "label": "Interested in", "placeholder": "Sofa, Bed, Wardrobe…", "required": false, "order": 3,
       "field_type": "select", "options": ["Sofas", "Beds", "Dining", "Wardrobes", "Other"]},
      {"key": "notes",     "label": "Tell us more", "placeholder": "Anything we should know?", "required": false, "order": 4, "field_type": "textarea"}
    ],
    "submit_button_label": "Get a quote",
    "thank_you_message": "Thanks — we'll reach out shortly.",
    "thank_you_url": null,
    "branding": {
      "logo_url": null,
      "accent_color": "#4F46E5",
      "show_powered_by": true
    }
  }
  ```
- The submission service from Step 2 now consults this config: every submitted field must be in the config's `fields` list; required fields must be present; `interest` value must be in `options` if the field is type `select`.
- Tests: defaults seeded on first read; update validation rejects unknown keys; public endpoint exposes safe subset; key lookup gates public endpoint.

Out of scope:

- No multi-widget per org (only one config). Multi-widget is a future surface (e.g. "Contact form" vs. "Newsletter form" vs. "Quote request" widgets).
- No A/B testing.
- No conditional fields ("show this field only if interest = Other").
- No CAPTCHA toggle here — Step 8.
- No frontend — Step 4.

## The `widget_configs` table

```sql
CREATE TABLE widget_configs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id) UNIQUE,  -- one config per org
    config      JSONB NOT NULL,                                     -- full document per the shape above
    updated_by  UUID REFERENCES users(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE widget_configs ENABLE ROW LEVEL SECURITY;
CREATE POLICY widget_configs_tenant_isolation ON widget_configs
    USING (org_id = current_setting('app.org_id', true)::uuid);
-- public read endpoint runs as a service role that bypasses RLS but
-- explicitly filters by the embed key's org_id, equivalent to RLS.
```

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/0XXX_add_widget_configs.py` | created |
| `api/src/app/core/embed/models.py` | modified — `WidgetConfig` |
| `api/src/app/core/embed/schemas.py` | modified — `WidgetConfigField`, `WidgetConfigBranding`, `WidgetConfigRead`, `WidgetConfigUpdate`, `WidgetConfigPublic` |
| `api/src/app/core/embed/config_service.py` | created |
| `api/src/app/core/embed/router.py` | modified — `GET/PUT /embed/config`, `GET /embed/config/public` |
| `api/src/app/core/embed/submissions.py` | modified — validate payload against config (only allowed keys, required ones present, enum values valid) |
| `api/tests/test_widget_config.py` | created |

**7 files, 1 migration.** Inside rule-8 budget.

## Plan

1. Migration. `widget_configs` table with the unique `org_id` constraint + JSONB column.
2. Define Pydantic schemas. `WidgetConfigField` includes `key`, `label`, `placeholder`, `required`, `order`, `field_type` (`text|email|tel|textarea|select`), optional `options` (for select). `WidgetConfigPublic` is the subset the widget gets (omits `updated_by`, `updated_at`, etc.).
3. `config_service.get_or_create(org_id)` — on miss, insert the default doc above.
4. `update()` — validate the incoming shape with Pydantic; reject unknown `key` values not in the allowed set `{full_name, phone, email, interest, notes}` (extension to custom fields = future task). Persist + bump `updated_at` + emit audit `embed.config.updated`.
5. Admin endpoints: standard JWT + permission gate.
6. Public endpoint: no JWT. Read header or query param key. Lookup → org. Fetch config. Return the `WidgetConfigPublic` projection. Set `Cache-Control: public, max-age=60` so the widget can cache.
7. Extend `submissions.submit()`: after key lookup, also load the config. Validate that every payload key is in the config's allowed fields. Required fields must be non-empty. `interest` if select-typed must be in `options`.
8. Tests.

## Tests

`api/tests/test_widget_config.py`:

- **Default seeded:** GET /embed/config on a fresh org returns the documented defaults.
- **Update happy path:** PUT with `submit_button_label: "Request Quote"` → GET reflects.
- **Update rejects unknown field key:** PUT with `fields: [{key: "ssn", …}]` → 422.
- **Public endpoint via key:** GET /embed/config/public?key=… returns the same shape minus admin metadata.
- **Public endpoint without key:** GET /embed/config/public → 400.
- **Public endpoint with invalid key:** → 401.
- **Submission respects config:** widget POSTs with `ssn: "…"` → 422 (field not in config). POST with `interest: "Plumbing"` when options is `[Sofas, Beds, ...]` → 422.
- **Config update audit:** `embed.config.updated` event emitted.
- **RLS:** Org A's PUT cannot affect Org B's config.
- **Permission:** Employee PUT → 403.

## Smoke

```powershell
$token = "<owner JWT>"
$secret = "<pk_live_… from Step 1 smoke>"

curl http://localhost:8000/api/v1/embed/config -H "Authorization: Bearer $token"
# Expect default JSON config.

curl -X PUT http://localhost:8000/api/v1/embed/config `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -d '{"submit_button_label":"Request a Quote","branding":{"accent_color":"#B45309","show_powered_by":true}}'

curl "http://localhost:8000/api/v1/embed/config/public?key=$secret"
# Expect public projection of the updated config.

# Submission still works
curl -X POST http://localhost:8000/api/v1/embed/leads `
  -H "X-FurniCRM-Key: $secret" `
  -H "Content-Type: application/json" `
  -d '{"full_name":"Asha","phone":"+919876543210","interest":"Sofas","honeypot":"","rendered_at":"2026-05-22T11:00:00Z","attribution":{}}'
# Expect 201.

# Submission with disallowed field
curl -X POST http://localhost:8000/api/v1/embed/leads `
  -H "X-FurniCRM-Key: $secret" `
  -H "Content-Type: application/json" `
  -d '{"full_name":"Asha","phone":"+919876543210","ssn":"123","honeypot":"","rendered_at":"2026-05-22T11:00:00Z","attribution":{}}'
# Expect 422.
```

## Risks

- **Config shape ossifies quickly:** JSONB is flexible but the widget bundle hardcodes the fields it knows how to render. Adding a new `field_type` requires bumping the widget version. Document the v1 supported types in `schemas.py` so contributors don't add types without bumping the bundle.
- **Default config exposes more than minimum viable** — `email` and `notes` are optional but present. If an org wants only name + phone, they need to manually delete them. Acceptable; the Settings UI in Step 4 lets them.
- **Public endpoint caching:** the widget caches the config for the session; on key revoke the cached config still works for that page-load. Acceptable — revocation effectiveness is at the submission endpoint, not the config endpoint.
- **Interest field validation tradeoff:** orgs may want free-text interest while keeping select for the dropdown. v1 forces one or the other (set `field_type`); a "select with allow-other" pattern is a follow-on.

## Rollback

Reverse migration. Delete new files. Submission service reverts to the looser Step-2 validation. Widget keeps rendering against the previous default shape (it gracefully ignores missing config-public endpoint by falling back to defaults — implement that in Step 6).
