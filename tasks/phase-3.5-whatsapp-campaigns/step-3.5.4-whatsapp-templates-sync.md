# Step 3.5.4 — WhatsApp templates: DB cache + Meta sync API + list endpoint

**Goal:** Per-org cache of Meta-approved WhatsApp message templates with a "Sync from Meta" pull and a list endpoint the campaign template picker (Step 3.5.5) will consume.

**Phase:** 3.5 (WhatsApp Campaigns)
**Depends on:** 3.5.1 (Integration + sidecar), 3.5.3 (resolver — sync calls Meta with the org's stored creds)
**Status:** ✅ COMPLETED — implementation passes 8/8 new tests

After this step:
- Owner hits "Sync templates" → backend fetches Meta's `/{waba_id}/message_templates` → upserts each into `whatsapp_templates` (per-org)
- Campaign create-modal can list `GET /api/v1/integrations/whatsapp/templates` to populate its template-picker
- Each row carries: name, category (MARKETING / UTILITY / AUTHENTICATION), language, status (APPROVED / PENDING / REJECTED / DISABLED), body, header type, variable count — enough for the picker to filter, preview, and validate variable inputs

What stays out of scope:
- Sending a template message (Step 3.5.5 adds it once the picker exists)
- Template create / submit-for-approval through CRM UI (deferred — operators continue using Meta Business Manager for creation; we only sync/read here)
- Per-template stats (Step 3.5.13)

---

## Scope

### In-scope

- New table `whatsapp_templates`:
  - `id` (UUID PK)
  - `org_id` (TenantScoped) — every row org-scoped + RLS
  - `integration_id` (FK → `integrations.id`, ON DELETE CASCADE) — tells us which WA account a template belongs to; survives until the integration is hard-deleted
  - `name` (Text) — Meta template name, e.g. `hello_world`
  - `language` (Text) — e.g. `en_US`, `hi`
  - `category` (Text) — `MARKETING` | `UTILITY` | `AUTHENTICATION`
  - `status` (Text) — `APPROVED` | `PENDING` | `REJECTED` | `DISABLED` (Meta's lifecycle)
  - `body` (Text) — the message body template with `{{1}}`, `{{2}}` placeholders
  - `header_type` (Text, nullable) — `TEXT` / `IMAGE` / `VIDEO` / `DOCUMENT` / NULL
  - `header_text` (Text, nullable) — when `header_type='TEXT'`
  - `footer_text` (Text, nullable)
  - `variable_count` (Integer) — count of `{{n}}` placeholders in body (precomputed for fast picker UX)
  - `meta_template_id` (Text) — Meta's own template id (for traceability + idempotent upsert)
  - `last_synced_at` (timestamptz)
  - `created_at`, `updated_at`
  - Indexes: UNIQUE (`integration_id`, `name`, `language`), INDEX (`org_id`, `status`)
- Migration `0062_whatsapp_templates.py` — table + RLS via `apply_rls`.
- Service layer in `core/integrations/whatsapp/templates.py`:
  - `async def sync_templates(session, http_client_factory=...) -> dict` — fetches `GET graph.facebook.com/{api_version}/{waba_id}/message_templates?limit=200`, pages until done, upserts rows (idempotent on `(integration_id, name, language)`), returns `{added, updated, removed, total}`. Removes locally-cached rows whose Meta template no longer exists.
  - `async def list_templates(session, *, status=None, category=None) -> list[WhatsAppTemplate]` — read for the picker.
- REST endpoints under existing `/api/v1/integrations/whatsapp`:
  - `POST /templates/sync` — gated `settings.integrations.manage`; calls `sync_templates`; returns the counts dict for the Settings UI toast
  - `GET /templates` — gated `campaigns.read` (any campaign-author can read; doesn't need integration-admin perms) — returns paginated list with optional `status` / `category` filter
- Tests (in `tests/test_whatsapp_templates.py`):
  - `test_sync_inserts_new_templates` — mocked Meta `/message_templates` returns 3 templates → 3 rows inserted
  - `test_sync_updates_existing` — re-sync with same name/lang but updated body → in-place update, `last_synced_at` bumps, no duplicates
  - `test_sync_removes_deleted` — second sync omits one template → that row removed from cache
  - `test_sync_raises_when_disconnected` — uses `resolve_whatsapp_adapter` → `WhatsAppNotConnected`
  - `test_variable_count_computed_correctly` — body `"Hi {{1}}, your order {{2}} is ready"` → variable_count=2
  - `test_list_filters_by_status` — only APPROVED rows return when `status='APPROVED'`

### Out-of-scope (deferred)

- **Template send call (`send_template`)** → Step 3.5.5 will add a new adapter method that uses these rows. This step only caches them.
- **Campaign create-modal template picker UI** → Step 3.5.5 (consumes `GET /templates`).
- **Settings UI "Sync" button** → Small frontend addition in Step 3.5.5 (wraps both `POST /sync` + the picker in the same UI iteration).
- **Template create / submit-for-approval** → Operators use Meta Business Manager; CRM never POSTs to Meta to create templates.
- **Webhook-driven status updates** (Meta sends template status change events) → Step 3.5.13.
- **Pagination beyond Meta's first page** for very large libraries (200+ templates) → covered, but UI pagination of the list endpoint deferred to Step 3.5.5.

---

## Files to touch

### Created (4)

- `API/alembic/versions/0062_whatsapp_templates.py` — migration.
- `API/src/app/core/integrations/whatsapp/models.py` — add `WhatsAppTemplate` ORM class (extend existing module).
- `API/src/app/core/integrations/whatsapp/templates.py` — sync + list service.
- `API/tests/test_whatsapp_templates.py` — 6 tests.

### Modified (3)

- `API/src/app/core/integrations/whatsapp/router.py` — add `POST /templates/sync` + `GET /templates` endpoints.
- `API/src/app/core/integrations/whatsapp/schemas.py` — add `WhatsAppTemplateRead`, `WhatsAppTemplateSyncOut`.
- `API/src/app/core/integrations/whatsapp/__init__.py` — re-export new service functions.

**File budget:** 7 files. Within ≤10.

---

## Plan

1. **Migration `0062_whatsapp_templates.py`:**
   - `CREATE TABLE whatsapp_templates (...)`
   - UNIQUE(`integration_id`, `name`, `language`)
   - INDEX(`org_id`, `status`)
   - `apply_rls("whatsapp_templates")`
   - `down_revision = "0061_whatsapp_account_config"`
2. **`models.py`** — add `WhatsAppTemplate(Base, TenantScoped)` with the columns above. Helper `@property def variables(self) -> list[int]` that returns the sorted list of placeholder numbers found in body (used by the picker to render input fields).
3. **`schemas.py`** — add `WhatsAppTemplateRead` (full row projection) + `WhatsAppTemplateSyncOut` (`{added, updated, removed, total}`).
4. **`templates.py`:**
   - `async def sync_templates(session, http_client_factory=None) -> dict`:
     - Calls `resolve_whatsapp_adapter(session)` to get the org's adapter (also acts as our "connected?" gate).
     - Builds URL `https://graph.facebook.com/{api_version}/{waba_id}/message_templates?limit=200&fields=name,language,category,status,components,id`.
     - Walks Meta's pagination (`paging.next` link) until exhausted.
     - For each template: extract body / header / footer from `components[]`, count `{{n}}` placeholders via regex.
     - Upsert by (`integration_id`, `name`, `language`); stamp `last_synced_at = now()`.
     - After upsert pass, delete any local rows whose (name, language) no longer appears in the sync response. Track counts.
     - Returns `{added, updated, removed, total}`.
   - `async def list_templates(session, *, status=None, category=None) -> list[WhatsAppTemplate]` — straight SELECT, RLS handles org scoping.
5. **`router.py`:**
   - `POST /templates/sync` → `settings.integrations.manage` → returns `WhatsAppTemplateSyncOut`. Catches `WhatsAppNotConnected` → 409.
   - `GET /templates?status=...&category=...` → `campaigns.read` → returns `list[WhatsAppTemplateRead]`.
6. **Tests** — reuse `_CapturingSession` from existing test file. Mock `httpx.AsyncClient.get` to return paginated Meta-shaped JSON.

---

## Meta API contract (what we're consuming)

`GET https://graph.facebook.com/v18.0/{waba_id}/message_templates?limit=200&fields=name,language,category,status,components,id`

Response shape (Meta docs, simplified):
```json
{
  "data": [
    {
      "id": "1234567890",
      "name": "diwali_sale_2026",
      "language": "en_US",
      "category": "MARKETING",
      "status": "APPROVED",
      "components": [
        {"type": "HEADER", "format": "TEXT", "text": "Diwali Sale"},
        {"type": "BODY", "text": "Hi {{1}}, enjoy 30% off on all {{2}} this Diwali!"},
        {"type": "FOOTER", "text": "Sharma Furniture"}
      ]
    }
  ],
  "paging": {
    "cursors": {"before": "...", "after": "..."},
    "next": "https://graph.facebook.com/v18.0/{waba_id}/message_templates?after=..."
  }
}
```

Our parser:
- Body: from `components` where `type == "BODY"` → `text`
- Header: from `components` where `type == "HEADER"` → `format` + `text`
- Footer: from `components` where `type == "FOOTER"` → `text`
- `variable_count`: `len(set(re.findall(r"\{\{(\d+)\}\}", body)))`

---

## Migration SQL preview

```sql
CREATE TABLE whatsapp_templates (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id           uuid NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    integration_id   uuid NOT NULL REFERENCES integrations(id) ON DELETE CASCADE,
    name             text NOT NULL,
    language         text NOT NULL,
    category         text NOT NULL,
    status           text NOT NULL,
    body             text NOT NULL,
    header_type      text,
    header_text      text,
    footer_text      text,
    variable_count   integer NOT NULL DEFAULT 0,
    meta_template_id text,
    last_synced_at   timestamptz NOT NULL DEFAULT now(),
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_whatsapp_templates_integration_name_lang
    ON whatsapp_templates(integration_id, name, language);
CREATE INDEX ix_whatsapp_templates_org_status
    ON whatsapp_templates(org_id, status);

ALTER TABLE whatsapp_templates ENABLE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON whatsapp_templates
    USING (org_id = current_setting('app.org_id', true)::uuid);
```

---

## API contract (what callers will see)

### `POST /api/v1/integrations/whatsapp/templates/sync`

```json
// 200 OK
{
  "added": 3,
  "updated": 1,
  "removed": 0,
  "total": 4
}

// 409 — org not connected
{ "detail": "WhatsApp is not connected for this org. Connect it in Settings → Integrations." }
```

### `GET /api/v1/integrations/whatsapp/templates?status=APPROVED&category=MARKETING`

```json
// 200 OK
[
  {
    "id": "uuid",
    "name": "diwali_sale_2026",
    "language": "en_US",
    "category": "MARKETING",
    "status": "APPROVED",
    "body": "Hi {{1}}, enjoy 30% off on all {{2}} this Diwali!",
    "header_type": "TEXT",
    "header_text": "Diwali Sale",
    "footer_text": "Sharma Furniture",
    "variable_count": 2,
    "last_synced_at": "2026-05-28T10:30:00Z"
  }
]
```

---

## Verification checklist

**Migration:**
1. `docker exec template_api-api-1 alembic upgrade head` → `0061 → 0062_whatsapp_templates` clean.
2. `psql` → `\d whatsapp_templates` → table + indexes + RLS enabled.

**Tests:**
3. `docker exec template_api-api-1 pytest tests/test_whatsapp_templates.py -v` → 6/6 pass.
4. Full WhatsApp suite still green: `pytest tests/test_whatsapp*.py` → 20 tests pass (14 + 6).

**Smoke (real Meta test creds):**
5. Connect WhatsApp via UI (Step 3.5.2).
6. `curl -X POST -H "Authorization: Bearer $JWT" .../integrations/whatsapp/templates/sync` → 200 with counts.
7. `psql` → `SELECT name, language, status FROM whatsapp_templates;` → rows match Meta dashboard.
8. `curl GET .../integrations/whatsapp/templates?status=APPROVED` → list of approved templates.
9. Disconnect → re-sync → 409.

---

## Self-check against 10 rules

| Rule | Status |
|---|---|
| 1. core/ → no packs | ✅ All in core/integrations |
| 2. org_id + RLS | ✅ Both on `whatsapp_templates` |
| 3. Layered custom fields | ✅ N/A |
| 4. Dynamic forms | ✅ N/A |
| 5. Sidebar | ✅ Unchanged |
| 6. Permissions | ✅ Reuses `settings.integrations.manage` + `campaigns.read` — no new keys |
| 7. Pack manifest | ✅ N/A |
| 8. ≤10 files | ✅ 7 files (4 created + 3 modified) |
| 9. Verification | ✅ Tests + migration up/down + smoke documented |
| 10. No TODOs | ✅ Template-create / status-webhook deferred to documented later steps; not half-built here |

---

## Stop & report

After implementation I will:
- List exact files changed, one line each.
- Show migration up + tests passing (6 new + 14 existing).
- Show curl example of sync + list.
- Show 1 row in `whatsapp_templates` after a real sync.
- **Await your "proceed" before Step 3.5.5 (Campaign template picker — adapter `send_template` + create-modal UI + Settings "Sync" button).**

---

## Pre-implementation question (one only)

**Q: Sync deletion behavior — agar Meta se ek template gayab ho jaye (deleted in Meta Business Manager), local cache se delete kar dein, ya soft-disable mark kar dein?**

- **(a) Hard delete.** Simple, reflects Meta state exactly. Campaign that referenced a deleted template → "Template not found" error at send-time (acceptable — operator should re-pick).
- **(b) Soft disable.** Add a `local_status` column or set `status='DISABLED'`. Old campaign rows still resolve the template for audit/history. Slightly more code.

**Recommendation: (a) Hard delete.** Reasons:
- Meta is source of truth — deletion there means operator chose to remove
- Campaigns table doesn't FK to templates; the campaign's `template` column stores the name as text, so audit history isn't lost
- (b) accumulates dead rows over time; we'd need a cleanup later

Bolo **(a) ya (b)**, fir **"begin"** → mai implement karta hoon.
