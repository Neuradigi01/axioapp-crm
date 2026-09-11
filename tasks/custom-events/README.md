# Custom Events — user-defined triggers for workflows and templates

A new `core/public_ingest/` module that **absorbs `core/embed/` + `core/ai_assistants/public_context.py` + a new `custom_events/` sub-module** into one public-authenticated surface: one API-key table (`tbl_api_keys`, renamed from `tbl_embed_keys` — already retrofitted with `resource_type` + `resource_id` in migration `0201`), one HMAC verifier, one Redis-backed rate limiter + idempotency store, one audit contract. On top of that, custom events let each org define **their own event types**, fire them from any external system via `POST /api/v1/events/track` (Segment / Customer.io / HubSpot pattern), and trigger workflows + merge event-payload variables into templates.

## Why this track exists

Today (audit date 2026-09-11) the CRM supports **50+ hardcoded system events** declared in `core/events/event_catalog.py` — every event a workflow can trigger on must be added by an engineer, deployed, and shipped. Clients cannot:

- Define events that reflect their business (`custom.order.paid`, `custom.nps.submitted`, `custom.demo.requested`).
- Fire events into the CRM from their existing tools (Shopify, Stripe, Zapier, Make, custom backends).
- Merge event-payload data into templates (`{{event.order_total}}`, `{{event.rating}}`).

**Client requirement (2026-09-11):** "they can also have their custom conditions to create templates and workflows and send templates on a particular custom-created event."

Standard CRMs solve this with a **user-defined event catalog** + a **public tracking endpoint** + a **payload schema**:

| Product | Ingest surface | Namespace strategy | Auto-create contact on unseen identifier? |
|---|---|---|---|
| HubSpot Custom Behavioral Events | `POST /events/v3/send` | System auto-prefixes with `pe<portalId>_` (invisible to user) | ✓ Default on |
| Salesforce Platform Events | Platform Events API | Object name auto-suffixed `__e` | ✓ |
| Segment / Customer.io | `analytics.track(event, properties)` | Free-form (users occasionally shoot themselves) | ✓ Default on |
| ActiveCampaign | `POST /trackers/event` | Free-form | ✓ |
| Zoho CRM | Workflow triggers via Notification API | Suffix-based | ✓ |

**Decision D1 (locked):** system auto-prefixes user event names with `custom.` internally. User types `order.paid`, system stores + fires as `custom.order.paid`. Picker displays `order.paid` (grouped under "Custom events"). Collision with system events impossible by construction.

**Decision D2 (locked):** auto-create contact on unseen `email` / `phone` by default; tag `source='event_ingest'` + `created_from_event_id=<occurrence_id>`; per-API-key `auto_create_contacts` boolean (default `true`) lets security-conscious tenants opt out.

## What changes

- **Rename `tbl_embed_keys` → `tbl_api_keys`.** Table is already multi-resource (`resource_type` values `lead_form` / `ai_assistant` + CHECK constraint added by migration `0205_extend_embed_keys_ai.py` — correct number verified against source). We add `'events'` to the CHECK; add columns `auto_create_contacts BOOLEAN DEFAULT TRUE`, `default_owner_user_id UUID NULL FK tbl_users`, `hmac_required BOOLEAN DEFAULT TRUE` (events keys default enforce signing; embed/ai_assistant keep whatever they had), `mode ENUM('live','test') DEFAULT 'live'`, `key_lookup_hash BYTEA NOT NULL` (Fernet-encrypted HMAC-of-key for O(1) prefilter — pepper in `secrets.enc.env`, rotatable), `old_key_hash BYTEA NULL` + `old_key_expires_at TIMESTAMPTZ NULL` (24h grace), `hmac_secret_encrypted BYTEA NULL` (Fernet-encrypted; NEVER re-revealable after issuance; `SecretStr` on Pydantic + explicit `exclude=True`), `rate_limit_per_minute INT DEFAULT 100` (unit corrected to per-minute for events keys; embed keys keep per-hour semantics). Repoint the two existing callers (`core/embed/`, `core/ai_assistants/public_context.py`) to the new module in Step 2.
- **New `core/public_ingest/` module** — public-authed routers only. **Shared primitives (rate_limit, idempotency, hmac_verify) live in `api/src/app/shared/`, NOT inside `public_ingest/`** — they are stateless helpers reused by future internal-webhook receivers (Stripe, Twilio) too:
  - `api/src/app/shared/rate_limit.py` — extended (existing file). Sliding-window Redis-backed counters per key + per IP + per identifier. Trusted-proxy list explicit in `config.env` (`TRUSTED_PROXIES=`); startup fail-loud in prod if empty. XFF chain parsed from right; stop at first non-trusted. Fail-mode explicit per surface: **events endpoint fails CLOSED (503) on Redis outage** — retryable + audit-logged.
  - `api/src/app/shared/idempotency.py` — new. Redis-backed 24h TTL LRU (`noeviction` policy or dedicated Redis DB). Accepts key via `Idempotency-Key` header OR body field `messageId`. **Scope = `(org_id, api_key_id, key)`** — never cross-key collision within an org. Regex-validated `^[A-Za-z0-9_.:\-]{1,128}$` before Redis put.
  - `api/src/app/shared/hmac_verify.py` — new. Extracted from `core/integrations/meta/webhook.py` + `core/integrations/whatsapp/*`. `verify_signature(raw_body: bytes, signature_header: str, secret: str, timestamp_header: str)` — constant-time compare via `hmac.compare_digest`, timestamp window ±2.5 min (5-min window with clock-skew allowance = window/2), nonce cache in Redis TTL=5min. **Consumes raw body BEFORE FastAPI Pydantic parse** (via middleware saving raw bytes into `request.state.raw_body`) — documented explicitly so implementers don't fall into the double-read gotcha.
  - `core/public_ingest/api_keys/` — moved from `core/embed/` (models, schemas, service, router, DAL for CRUD + reveal). Fast HMAC-of-full-key prefilter (indexed `key_lookup_hash` — full key body, not prefix) + Argon2id verify (defeat Argon-DoS; at most one Argon call per request). Sequential rotation guard: if `old_key_hash IS NOT NULL AND old_key_expires_at > now()`, second rotation returns 409 "grace window still active — force-purge or wait." Alert Celery beat task at 12h mark if any request still using `old_key_hash`.
  - `core/public_ingest/embed/` — the existing embed lead-form surface, now mounted under the shared auth + rate limit. **`tbl_public_ingest_log`** (renamed from `tbl_embed_submissions_log`) becomes the shared rejection/audit log for all three surfaces — the sixth cascade table on org delete.
  - `core/public_ingest/ai_assistants/` — moved from `core/ai_assistants/public_context.py`. Endpoints unchanged.
  - `core/public_ingest/custom_events/` — new (definitions CRUD + occurrences). Files: `models.py, schemas.py, router.py, service.py, data_access.py, tasks.py` — six files max (fold `workflow_cascade` + `schema_review` into `service.py`; `archive_task` + monthly job into `tasks.py`).
  - `core/public_ingest/ingest/` — new. Files: `router.py, service.py, payload_validator.py` (pure — no DB), `contact_resolution.py` (calls into `core/contacts/service.py`, never direct-inserts). Step 7 pre-split into 7a (auth + HMAC + idempotency + rate) / 7b (payload validation + contact resolution) / 7c (bus publish + occurrence persistence + response shaping).
- **Two new tables (v1 — dropped the version table per architect):**
  - `tbl_custom_events` — per-org event definitions (`id, org_id, name` [stored WITHOUT `custom.` prefix — added at publish time by a single `add_prefix()` helper; cleaner than N strip-sites], `display_label, category, is_active, created_by, payload_schema JSONB, schema_updated_at`). Partial-index `UNIQUE (org_id, LOWER(name)) WHERE is_active = true` (allows re-creation after soft-delete; case-insensitive). NFKC-normalize + ASCII-only regex `^[a-z][a-z0-9_]{0,39}(\.[a-z][a-z0-9_]{0,39}){0,3}$` at input (rejects Cyrillic-homoglyph collisions). `is_active` **soft-delete only** — hard delete not allowed. Schema-edit history captured via existing `core/audit/` module (audit event `custom_event.schema.edited` with before/after diff); no separate version table.
  - `tbl_custom_event_occurrences` — every fired event (`id, org_id, event_id, payload_schema_snapshot JSONB` [denormalised — occurrence carries its own fire-time schema, no version-table pointer], `payload JSONB, contact_id NULLABLE FK, external_id VARCHAR(128) NULLABLE` [for cookie/utk-style anonymous identifiers — unlocks Shopify-cart-abandonment class], `source, mode` [`live`|`debug`], `ip_hashed BYTEA` [per-org rotated pepper stored Fernet-encrypted; annual rotation], `is_test BOOLEAN`, `fired_at`). 90-day retention; older rows **month-partitioned** and archived monthly to `tbl_custom_event_occurrences_archive` (RLS enforced; indexed on `(org_id, event_id, fired_at DESC)`). Service function `list_occurrences(org_id, event_id, since)` federates primary + archive when `since` reaches past 90 days.
  - **Test-fire results NOT in occurrences** — separate table `tbl_custom_event_test_runs (id, org_id, event_id, fired_by_user_id, payload_snapshot, rendered_actions_preview JSONB, fired_at)` with 7-day retention. Dry-run output stored here; "Test fires" tab reads this table. Prevents live-occurrence pollution.
  - **Contact auto-create race handling:** unique constraint on `(org_id, LOWER(email))` and `(org_id, phone)` already exists on `tbl_contacts`; ingest wraps auto-create in `try INSERT → on IntegrityError, SELECT and repoint occurrence.contact_id`. Test asserts two concurrent unseen-email fires produce ONE contact + TWO occurrences pointing at it.
- **Public ingest endpoint** `POST /api/v1/events/track`:
  ```json
  { "event": "order.paid",                // system stores as "custom.order.paid"
    "properties": {"total": 129.99, "currency": "USD"},
    "contact_id": "uuid" | "email": "..." | "phone": "...",
    "messageId": "optional-idempotency-key"  // OR Idempotency-Key header
  }
  ```
  Auth: `Authorization: Bearer pk_live_<key>` (or `pk_test_<key>` for debug-mode keys — see below). HMAC optional but **required if `properties` will be merged into any outbound-message workflow action** (see B-SEC-2 below); the flag lives on the key row.
- **Payload validation.** Flat JSON-Schema-lite: `{ property_name: { type: "string"|"number"|"boolean"|"date"|"email"|"url"|"text", required: bool, enum: [...]?, max_length: int? } }`. Extra keys stored verbatim; only declared keys surface in the picker. Caps: **payload total 64KB** (413), **per-property value 4KB** (`"string"`) / **8KB** (`"text"`), **property count 50**, **`enum` array cap 50 values × 128 chars each**, **`"url"` scheme allowlist HTTPS only, no server-side fetch, length 2048**, **`"email"` bounded-parser length ≤254 (RFC 5321), no regex** (defeat ReDoS), **`"date"` ISO-8601 strict-parse**, **`"number"` stored as `Decimal` string (money precision)**. Property names sanitized (regex `^[a-z][a-z0-9_]{0,63}$`) before storage. **Renderer additionally truncates per-value output at 4KB with `... [truncated]` marker** — defense in depth so SMS/WhatsApp bombs die at render time even if ingest was somehow bypassed. `{{event.*}}` values are HTML-escaped by default in HTML channels; `|raw` opts in; SMS/WhatsApp channels strip control chars + Unicode RTL-override chars.
- **Reserved-name enforcement.** Create-time reject if the user-visible (unprefixed) name matches any system event in `core/events/event_catalog.ALL_EVENTS` after normalization. Belt for D1's auto-prefix suspenders.
- **Contact resolution:**
  - `contact_id` provided → validated to belong to key's org. **Cross-tenant `contact_id` returns uniform 200 with `contact_id=NULL`** (NOT 400 — 400 was an enumeration oracle). Attempted-cross-tenant logged internally for anomaly detection.
  - `email` / `phone` provided → looked up in key's org. **On miss, IF key's `auto_create_contacts=true`, contact created via `core/contacts/service.create_contact_service()` — NEVER direct DAL insert.** This routes through domain blocklists, consent gates, dedup heuristics, custom-field defaults, marketing-opt-in defaults, and **fires `contact.created` on the bus** so downstream welcome workflows trigger. If `auto_create_contacts=false` → occurrence stored with `contact_id=NULL`.
  - Auto-created contact gets `source='event_ingest'`, `created_from_event_id=<occurrence.id>`, `owner_id = key.default_owner_user_id` (per-key column set by Owner at key creation; validated on both create AND on every ingest that it's an active in-org user; **fallback = unassigned/round-robin per org config**, NEVER `org Owner` — dumping everything on Owner is a footgun). Frontend contacts source-filter dropdown + reporting groupings wired in Step 15 to render "Event ingest" as a first-class source (avoids "Other" bucket).
  - `email` / `phone` normalization: lowercase + trim email, E.164 phone with `phonenumbers` library.
  - **Contact-enumeration mitigation:** uniform 200 response regardless of match/miss/auto-create (including cross-tenant `contact_id`). Per-key rate limit on `email`/`phone` lookups is **10/min** vs 100/min for `contact_id`; **per-identifier throttle** (same email/phone > 2/min = 429) prevents systematic sweeps by a compromised-key holder. Misses logged with identifier-hash for anomaly detection.
  - **`pk_test_*` keys never auto-create real contacts** — test-mode occurrence gets `contact_id` from lookup only; miss = `contact_id=NULL` regardless of key's `auto_create_contacts` flag. Prevents production-contact pollution from debug integrations.
- **HTML escape on render (B-SEC-2).** The template renderer HTML-escapes `{{event.*}}` values in HTML-channel templates by default (email HTML body). Explicit `{{event.value|raw}}` opts in (Handlebars / Jinja convention). Occurrence detail page renders payload previews with Angular `[textContent]`, never `[innerHTML]`. SMS/WhatsApp channels strip control chars + Unicode direction-override chars.
- **Bridge into workflows.** Custom events flow through the existing bus (`core/events/bus.publish`). No double-publish. A **service-layer** `core/public_ingest/custom_events/service.list_catalog_for_org(org_id)` merges system events + custom events for the trigger picker; `core/automation/event_catalog.list_catalog()` **stays pure** (module-import contract preserved per Architect finding).
- **Bridge into variables registry.** `tasks/variables-unification/` Step 5 handles reading `tbl_custom_events.payload_schema` when `event=<custom.name>` is passed. If Track A hasn't shipped, this track ships a minimal patch to the workflows trigger picker only.
- **Workflow lifecycle:**
  - Delete custom event (`is_active=false`) → auto-disable dependent workflows with audit note `custom_event.deleted.workflow_disabled`.
  - Re-activate event (create again with same name → new version) → dependent workflows STAY disabled; Owner sees a "1 workflow is disabled waiting on this event — re-enable?" prompt in the event detail page. (Auto-re-enable is footgun-y; opt-in.)
  - Schema rename that removes a payload key → walk dependent workflows/templates for `{{event.<removed_key>}}` references; publish a "review needed" warning on the workflow, don't auto-disable.
- **Owner vs Admin split (B-SEC-7).** Admin can **create + view + test-fire** custom events. **Only Owner can edit schema, soft-delete, or re-activate.** API keys are Owner-only entirely (already the pattern for embed keys via `settings.integrations.embed.manage`; extended to `settings.integrations.api_keys.manage`).
- **Test-fire = synthetic queue.** Test-fire does not create a live occurrence and does not fire real workflow actions (no emails / SMS / WhatsApp / webhook). It runs the event through the workflow **dry-run engine** (already exists in `core/workflows/dry_run.py`) and shows the rendered outputs in a "Test fires" tab on the event detail page. Matches Stripe / Segment / HubSpot debugger UX.
- **Live vs debug keys.** Two prefixes: `pk_live_*` (real workflows fire) and `pk_test_*` (workflows run in dry-run mode; occurrences stored in `tbl_custom_event_test_runs` NOT the live occurrences table; hidden from live tab). One key row, `mode` column. **Separate rate-limit buckets** for live vs test (test = 20/min per key + 1000/day hard cap; live = 100/min). Test keys cannot `auto_create_contacts`. Prevents "I forgot which key I put in my Zapier config" incidents AND prevents test-key holder from burning production rate quota.

- **Dry-run engine dependency.** Step 4/7 test-fire requires a workflow dry-run engine. **Verified before implementation kickoff: `core/workflows/dry_run.py` does NOT exist today (only strings 'dry-run' in docstrings).** Step 0 of this track (added below) builds a minimal `dry_run_workflow(workflow_id, event_payload, occurrence_id)` that resolves + renders every action WITHOUT invoking outbound channels (no email/SMS/WhatsApp/webhook side effects). If the mini-track exceeds ~3 days, downgrade test-fire's v1 scope to "validate payload against schema + resolve contact + show parsed event envelope" (no action-preview).
- **Frontend Settings pages:**
  - `/user/settings/api-keys` (NEW, Owner-only) — CRUD keys with `mode`, `resource_type` (`events`/`lead_form`), `scopes` per resource_type (for events: `auto_create_contacts` toggle, `hmac_required` toggle), one-time reveal modal, revoke, rotate-with-grace (see below).
  - `/user/settings/custom-events` (NEW) — Admin+Owner view; Owner-edit; list + detail. Detail has tabs: Overview / Occurrences / Test fires / Workflows using this / How to fire (with pre-filled cURL + JS snippets in-session only — the key isn't stored decryptable, only remembered client-side after creation).
- **Rotate-with-grace flow (fixes B-SEC-1 rotation gap).** Rotate returns a new secret; old secret survives for **24h grace period** with an `expires_at` column; both hashes stored in the row (Argon2id-hashed each). Alerts owner "3 requests still using old key" 12h in.
- **Docs.** `/docs/api/events` public auto-generated from FastAPI OpenAPI + a `docs/quickstart/fire-your-first-event.md` with 4 examples (cURL, JS/Node, Python, Zapier "Webhooks by Zapier" step-by-step).

## What this track does NOT include

- **First-party Zapier / Make / n8n private apps.** Public `/events/track` works with any HTTP client, which is enough for Zapier's Webhooks and Make's HTTP module. Native apps are a separate GTM track (~1-2 weeks Zapier CLI + directory review).
- **Browser JS/mobile SDKs** (Segment `analytics.js` equivalents). Backend / webhook use is v1; browser SDK v2.
- **Event replay / retroactive triggering.** Workflow created after the event fired does not fire retroactively. Matches HubSpot / Salesforce.
- **Complex payload validation** beyond required-key / type / enum / basic format. No regex, no cross-field rules. Send bad type → 400 with schema-error.
- **Nested payload schemas in the picker.** v1 payload schemas are flat top-level primitives. Nested objects stored verbatim, not picker-visible. Follow-up track for dotted-path picker if demand exists.
- **Rate-limit tuning per event type.** All events on a key share the key's rate limit. Per-event overrides = v2.
- **Custom-event → outbound webhook** (HubSpot / Segment Destinations parity). This track is ingest-only. Schema carries `direction` column so an outbound track can share the table without a v2 migration; UI just doesn't expose it yet.
- **GDPR erasure of PII inside `payload` JSONB.** Nulling `contact_id` on contact-delete already implemented. Scrubbing known-PII keys from payload (email, phone in properties) is a follow-up (`gdpr-payload-scrub`) — noted.
- **Alerting on integration-error rate.** "Alert if >20% rejection over 24h" = future. Today: Settings page shows a "Recent errors" pill on the event card with the last 5 failure reasons.

## Multi-tenancy

- Every new / renamed table (`tbl_api_keys`, `tbl_custom_events`, `tbl_custom_event_schema_versions`, `tbl_custom_event_occurrences`, `tbl_custom_event_occurrences_archive`) has `org_id UUID NOT NULL FK tbl_organizations` + RLS from its first migration.
- `POST /events/track` resolves `org_id` from the API key alone. Never trust `org_id` in body.
- Custom-event names unique per org (via partial unique index on active rows).
- Every rate-limit / idempotency Redis key namespaced with `org_id` at prefix — no cross-org key collision even at cache layer.
- Occurrence rows visible only to their org via RLS.
- Deleting an org cascades all six tables + Redis prefix-scan-and-delete on org deletion.

## Locked design choices (won't relitigate during implementation)

| Decision | Why | Comparison |
|---|---|---|
| **D1: system auto-prefixes user event names with `custom.`** (invisible in UI) | User types `order.paid` → stored as `custom.order.paid`. Impossible to collide with system events. Belt: create-time rejection of names that would collide unprefixed. | HubSpot `pe<portalId>_` prefix pattern, invisible to user. |
| **D2: auto-create contacts on unseen email/phone by default** with `source='event_ingest'` + `created_from_event_id` | A workflow "send WhatsApp on order.paid" that silently drops on first-ever customer is worthless. Every incumbent auto-creates. Guardrail: `auto_create_contacts` per-key toggle (default true), source-tag for bulk purge. | HubSpot + Segment + Customer.io + Zoho all auto-create. |
| **Rename `tbl_embed_keys` → `tbl_api_keys`, extend existing `resource_type`, don't invent `scope` column** | Table is already multi-resource (0201). Two axes on one table = matrix of edge cases + rewritten CHECK constraint. Rename is one-time cosmetic cost; `resource_type` already carries the semantics. | Existing pattern in this codebase. |
| **Fold `api_keys` + `rate_limit` + `idempotency` + `hmac_verify` + `embed` + `custom_events` under `core/public_ingest/`** | One HMAC verifier, one rate limiter, one audit contract. Right now `embed/rate_limit.py` and `embed/log_service.py` are already reused by `ai_assistants/public_context.py` — the fold formalizes what's already true. | Stripe's Public API layer is one auth surface serving multiple resources. |
| **Idempotency + rate limits + HMAC nonces on Redis, not in-process** | Per-process cache = replay across workers, undercounted per-IP rate limits × N pods, lost idempotency on rolling deploy. Everything shared through Redis; namespaced by org. | Stripe, Segment, every serious ingest. |
| **HMAC signature optional at endpoint level, mandatory when key's `hmac_required` is true OR when payload will be merged into outbound messages** | Sane default for HTTP-only integrations; forced when the payload becomes trusted content (email/SMS/WhatsApp). | Stripe webhooks always signed; Segment `track()` optional. Middle ground here. |
| **Reserved-name list = every string in `core/events/event_catalog.ALL_EVENTS`, checked at create** | Belt to D1's suspenders. Custom event named `contact.created` (that would become `custom.contact.created`) still can't collide, but the reservation prevents user confusion. | Standard reservation. |
| **`Owner+Admin` view + create; `Owner-only` edit + delete + re-activate** | Custom events are workflow-trigger config = closer to security than business config (rogue Admin can silently break org's workflows). API keys stay Owner-only. | Splits align with existing `settings.integrations.embed.manage` (Owner) vs contact fields (Owner+Admin). |
| **Custom-event delete is soft; hard-delete forbidden** | Historical occurrences must render with fire-time schema — hard-delete breaks this. Soft-delete with partial-unique-index allows re-create. | Segment Protocols, HubSpot event history. |
| **Re-activation does NOT auto-re-enable dependent workflows** | Auto-re-enable is a footgun (silently starts firing after months of dormancy). Owner sees prompt on event detail page. | HubSpot Workflow Issues pane. |
| **Test-fire = synthetic queue (workflow dry-run), not `test=true` on live occurrence** | Live-occurrence-with-flag pollutes reports, invites "Test" click that actually sends emails. Dry-run mirror is what every debugger UX ships. | Stripe Dashboard test-mode, Segment Debugger, HubSpot Event Tester. |
| **`pk_live_*` vs `pk_test_*` key prefixes** with a single `mode` column | Prevents production-test key confusion. `pk_test_` keys route to dry-run engine regardless of workflow config. | Stripe convention, universally understood. |
| **`Idempotency-Key` header AND `messageId` body field both accepted** | Header is Stripe-consistent; body is Segment-consistent. Callers use whichever their SDK exposes; server picks header first if both present. | Stripe + Segment. |
| **Fast HMAC-of-key index for auth pre-filter, Argon2id only on match** | Argon2id is deliberately slow (~100ms). Without a pre-filter, attacker DoSes with 1000 rps of random tokens. HMAC-of-key stored in a separate indexed column (`key_lookup_hash`); Argon2id (`key_hash`) only checked on positive lookup. | Standard bearer-token DB pattern. |
| **Rotate-with-24h-grace** — both hashes stored + `old_key_expires_at` | Zero-downtime key rotation on client side. | Stripe API key rotation. |
| **Payload size cap 64KB; property name regex `^[a-z][a-z0-9_]{0,63}$`; property count cap 50** | Prevents JSON-bomb, prevents `{{event.'; DROP--}}` shenanigans, prevents 1000-key payloads flooding picker. | Segment 32KB cap, Customer.io 512KB — 64KB is in the middle. |
| **HTML escape `{{event.*}}` by default in HTML channels; `|raw` opts in; SMS/WhatsApp strip control chars + RTL override** | Payload is attacker-controllable if any of the caller's webhook sources is compromised (Shopify store, intern's Zapier). Renderer is the last defense. | Handlebars + Jinja defaults. |
| **Occurrence retention 90 days → archive to indexed `_archive` table with RLS** | Balances audit trail + storage cost + compliance queries. Archive stays queryable. | HubSpot 90-day UI; Segment 30-day free / configurable paid. |
| **Occurrences store `schema_version_id_at_fire`** | Schema-version renderer walks the correct version at render time, not the current one. Renames don't retroactively break occurrence displays. | Segment Protocols versioning. |
| **Contact-merge cascade explicitly extended** | The existing merge cascade table list must include `tbl_custom_event_occurrences` (nulled or repointed). Test asserts this in Step 4. | Existing merge cascade pattern. |
| **GDPR contact-delete nulls `contact_id`; PII inside `payload` deferred** | Documented follow-up. Not silently ignored. | Follow-up `gdpr-payload-scrub` track. |

## Design decisions where I DISAGREED with a reviewer

- **Architect suggestion: fold `payload_schema` into `tbl_custom_field_definitions` with `entity='event:<name>'`.** Rejected. Custom events carry their own lifecycle (versioning, occurrences, categories, is_active, dependent-workflow bookkeeping) that don't map cleanly to per-entity custom fields. Cross-cutting "entity starts with event:" queries would be ugly. **The valuable reuse is the UI schema-builder widget, not the storage.** Track A already ships `<crm-custom-field-modal>` — this track imports the schema-builder pane from it for the payload-property editor. Storage stays separate; visual affordance shared.
- **Absence finding #18: "aspirational lead.\* in chatbots falsifies the headline promise."** Addressed in Track A (badge on unresolvable paths); full runtime coverage deferred as its own track. Not a Track B concern.
- **Architect L1: `pk_test_` / `pk_live_` prefix.** Adopted (see locked decisions) — I was wrong to defer; Stripe convention is well worth 4 hours of code.

## Absence (what the plan explicitly names — beyond the original list)

**Two-user races (in addition to the create-collision case in v1):**
- **Two Owners rotate API key simultaneously:** last write wins on the row's `key_hash` column; if we simply `UPDATE ... SET key_hash = ?`, one Owner's rotation clobbers the other. **Fix:** rotation uses optimistic lock on `updated_at`; second Owner gets 409 and refetches.
- **Two Owners edit event schema simultaneously:** schema-version bump is `INSERT INTO tbl_custom_event_schema_versions` with `version_number = current_max + 1`, wrapped in `SELECT ... FOR UPDATE` on the event row. Second concurrent edit gets `version_number = current_max + 2` (both preserved, latest wins for `current_schema_version_id` pointer). No lost work.
- **Test-fire during unsaved edit:** test-fire button disabled while dirty; tooltip "save the schema first."
- **Rate-limit under multi-pod load:** counters in Redis (Lua-scripted atomic increment + expiry), NOT in-process.
- **API key revocation mid-request:** in-flight request completes (key was verified at auth). Subsequent 401. Documented so callers know retries after revoke will 401.

**What starts and never finishes:**
- Bus publish outbox — existing outbox pattern from `core/events/bus` handles retry / DLQ.
- Idempotency Redis entries — 24h TTL.
- HMAC nonce cache — window-size TTL (5min).
- Test-fire dry-run tasks — Celery task with 60s deadline; timeouts logged.

**What gets created but never deleted / expired / re-claimed:**
- Occurrences → 90-day archive job (Step 11).
- Occurrences with `contact_id=NULL` from auto-create-disabled keys → separate lower rate limit (5/min per key) to prevent orphan flood.
- API keys → cascade on org delete; explicit revoke = hard delete (row + Redis prefix-scan); audit rows use `SET NULL` FK.
- Custom event definitions → cascade on org delete; explicit soft-delete only; hard-delete admin-only via DB (never UI).
- Schema versions → cap 50 per event; oldest squashed monthly.
- Dependent-workflow disabled-state → survives event re-activation; Owner opt-in re-enable.
- Contact merge → `tbl_custom_event_occurrences.contact_id` repointed via extended cascade list (test asserts).
- Contact delete → `contact_id` nulled; payload PII scrub deferred to follow-up track.
- Custom-event soft-delete → dependent workflows auto-disabled; Owner sees list in event detail page.
- `_archive` table → indefinite retention (compliance requirement); RLS enforced; indexed.

**What the caller asserts that we treat as proven:**
- `contact_id` in body: validated to belong to key's org.
- `email`/`phone`: normalized (lowercase / E.164) before lookup; case-sensitivity + international-format handled.
- `properties.*.value_type`: validated against schema; extra keys stored verbatim but not picker-visible.
- `messageId` / `Idempotency-Key`: length cap 128 chars; format not enforced beyond that; server keys `(org_id, key)`.
- HMAC secret: retrievable server-side (Fernet-encrypted column, not Argon-hashed — hash-only can't sign).
- Trusted proxy for `X-Forwarded-For`: explicit config list; if request doesn't come from a trusted proxy, `X-Forwarded-For` ignored and `request.client.host` used.

**Public surface / unauthenticated flooding:**
- Pre-auth per-IP rate limit: 20/min (aggressive; embed pattern uses 100 but this endpoint has bigger blast radius). Redis-backed.
- Post-auth per-key: 100/min default, configurable per key.
- Per-key rate limit on `email`/`phone` lookup: 10/min (contact-enumeration defense).
- Rejection responses log to `tbl_public_ingest_log` (existing embed pattern extended); alerts if `>20% rejection over 24h` = future ticket, noted.

## Cases

| Case | Behavior |
|---|---|
| Two users create same event name simultaneously | Partial-unique-index `WHERE is_active=true` → 409 to second. |
| Two Owners rotate key simultaneously | Optimistic lock on `updated_at` → 409 to second; second refetches. |
| Test-fire while user is mid-edit | Button disabled with tooltip. |
| Rate limit under 4 pods | Redis-shared counter — total 100/min across pods, not 400/min. |
| API key revoked mid-request | In-flight completes; subsequent 401. |
| Workflow depends on removed payload key | Renderer resolves empty; workflow flagged "review needed" (not disabled). |
| Contact merged | Occurrence repointed via extended cascade. |
| Contact deleted | `contact_id` nulled; payload preserved (PII scrub deferred). |
| Custom event re-activated after soft-delete | Dependent workflows STAY disabled; Owner prompted. |
| Two workflows trigger on same event | Both fire concurrently (existing workflow semantics). |
| `Idempotency-Key` OR `messageId` replay | Second call returns first response, 200 OK. |
| No idempotency key | No dedup; both create occurrences. |
| HMAC signature invalid | 401 pre-side-effect; no occurrence. |
| HMAC timestamp > 5min old OR nonce seen | 401; no occurrence. |
| Payload > 64KB | 413. |
| Payload property name doesn't match regex | 400. |
| `email` / `phone` lookup miss with `auto_create_contacts=true` | Contact created with `source='event_ingest'`; workflow fires. |
| `email` / `phone` lookup miss with `auto_create_contacts=false` | Occurrence stored with `contact_id=NULL`; workflows requiring contact skip. |
| Cross-tenant `contact_id` in body | 400. |
| `pk_test_*` key fires event | Occurrence `mode='debug'`; workflows dry-run; hidden from main tab. |
| `pk_live_*` key with `hmac_required=true` and no signature | 401. |

## Tests (named before code exists)

**Backend contract — auth + rate + idempotency:**
- `test_events_track_accepts_valid_payload_and_stores_occurrence`
- `test_events_track_401_missing_auth`
- `test_events_track_401_revoked_key`
- `test_events_track_403_wrong_resource_type` (key with `resource_type='lead_form'`)
- `test_events_track_401_hmac_required_but_missing`
- `test_events_track_401_hmac_invalid_signature_constant_time`
- `test_events_track_401_hmac_timestamp_out_of_window`
- `test_events_track_401_hmac_nonce_replay_within_window`
- `test_events_track_413_payload_too_large`
- `test_events_track_400_property_name_regex`
- `test_events_track_400_property_count_over_cap`
- `test_events_track_400_unknown_event`
- `test_events_track_400_inactive_event`
- `test_events_track_validates_payload_schema_types`
- `test_events_track_idempotency_key_header_dedup_across_workers` (Redis-backed)
- `test_events_track_messageId_body_field_dedup`
- `test_events_track_rate_limit_per_key_redis` (across simulated pods)
- `test_events_track_rate_limit_per_ip_pre_auth_redis`
- `test_events_track_rate_limit_email_phone_lookup_stricter`
- `test_events_track_argon2_dos_defeated_by_hmac_prefilter` (millions of random tokens don't cause CPU pileup)

**Contact resolution:**
- `test_events_track_contact_lookup_by_id_in_own_org`
- `test_events_track_contact_lookup_cross_tenant_id_rejected`
- `test_events_track_contact_lookup_by_email_normalized_lowercase`
- `test_events_track_contact_lookup_by_phone_normalized_e164`
- `test_events_track_email_miss_auto_creates_when_flag_true`
- `test_events_track_email_miss_null_contact_when_flag_false`
- `test_events_track_uniform_response_on_match_and_miss` (no enumeration oracle)

**Definitions:**
- `test_custom_event_create_auto_prefixes_with_custom_dot`
- `test_custom_event_create_rejects_reserved_name` (any string in `ALL_EVENTS` after normalization)
- `test_custom_event_create_partial_unique_allows_soft_delete_recreate`
- `test_custom_event_soft_delete_disables_dependent_workflows_with_audit`
- `test_custom_event_reactivation_does_not_auto_enable_workflows`
- `test_custom_event_edit_creates_new_schema_version_optimistic_lock`
- `test_custom_event_edit_schema_removal_flags_dependent_workflows`
- `test_custom_events_admin_can_create_view_test_fire`
- `test_custom_events_admin_cannot_edit_delete_reactivate` (Owner-only)
- `test_custom_events_rls_cross_tenant_read_empty`

**Workflow + variables integration:**
- `test_workflow_triggers_on_custom_event_end_to_end`
- `test_workflow_dry_run_engine_runs_for_pk_test_key_events`
- `test_variables_registry_appends_event_payload_for_custom_event` (Track A integration)
- `test_template_renders_custom_event_variable_html_escaped_by_default`
- `test_template_renders_custom_event_variable_raw_when_pipe_raw_used`
- `test_sms_channel_strips_control_and_rtl_chars_from_event_values`

**API keys:**
- `test_api_key_hmac_prefilter_index_lookup_is_o1`
- `test_api_key_migration_from_embed_keys_preserves_hashes_and_scopes`
- `test_api_key_hash_never_returned_after_reveal`
- `test_api_key_rotate_with_grace_both_hashes_valid_for_24h`
- `test_api_key_rotate_optimistic_lock_second_writer_409`
- `test_api_key_test_prefix_routes_to_dry_run`

**Contact-merge + delete cascade:**
- `test_contact_merge_repoints_custom_event_occurrences`
- `test_contact_delete_nulls_contact_id_preserves_payload`

**Archive:**
- `test_occurrence_archive_job_moves_rows_older_than_90d_with_rls_intact`
- `test_occurrence_archive_uses_indexes_not_full_scan`

**Playwright:**
- `custom_events_create_edit_delete_flow_admin_can_create_owner_only_edit`
- `api_keys_reveal_modal_one_time_display_and_test_key_dry_run`
- `workflow_trigger_picker_shows_custom_events_grouped`
- `payload_schema_builder_uses_shared_custom_field_widget`
- `test_fire_button_disabled_during_dirty_edit`
- `test_fires_tab_shows_dry_run_output_not_live_occurrences`
- `how_to_fire_tab_shows_pre_filled_key_in_session_only`
- `rotate_key_shows_grace_period_countdown`

## Theme groupings

| Theme | Steps | Why grouped |
|---|---|---|
| Fold + rename | 1-2 | Rename `tbl_embed_keys`→`tbl_api_keys`; move `embed/` + `ai_assistants/public_context.py` into `core/public_ingest/`; extract shared rate-limit/HMAC/idempotency |
| Shared infra (Redis) | 3 | Redis-backed rate limiter + idempotency + HMAC nonce cache |
| API keys hardening | 4 | HMAC prefilter, rotate-with-grace, live/test prefix modes |
| Custom events core | 5-6 | Definitions + schema versioning + occurrences schema |
| Public ingest endpoint | 7 | `POST /events/track` — auth + HMAC + idempotency + rate + validation + contact resolution + bus publish |
| Bridges + workflow lifecycle | 8-9 | Service-layer catalog merge, workflows auto-disable/re-enable prompt, variables registry payload-schema bridge |
| Retention + operations | 10 | Occurrence archive Celery beat + monthly schema-version squash |
| Frontend | 11-14 | API-keys page + Custom-events list + create/edit modal (reusing shared schema-builder) + detail page with 5 tabs |
| Docs + smoke | 15 | Public API reference + quickstart + Zapier walkthrough + end-to-end smoke |

## Steps index

| # | Title | Status | Effort |
|---|---|---|---|
| 0 | [Backend: minimal `core/workflows/dry_run.py` — render actions without outbound side-effects (Step 0 mini-track; skip if already exists)](step-0-workflow-dry-run-engine.md) | Pending | ~1½ days |
| 1 | [Backend: rename `tbl_embed_keys` → `tbl_api_keys`, add `resource_type='events'` + `auto_create_contacts` + `default_owner_user_id` + `hmac_required` + `mode` + `key_lookup_hash` + `old_key_hash`/`old_key_expires_at` + `hmac_secret_encrypted` + `rate_limit_per_minute`](step-1-rename-embed-to-api-keys.md) | Pending | ~1 day |
| 2 | [Backend: fold `core/embed/` + `ai_assistants/public_context.py` into `core/public_ingest/`; extract shared helpers to `api/src/app/shared/`](step-2-fold-public-ingest-module.md) | Pending | ~1½ days |
| 3 | [Backend: Redis-backed rate-limit + idempotency + HMAC nonce cache in `api/src/app/shared/`; trusted-proxy config; startup checks](step-3-redis-shared-infra.md) | COMPLETED | ~1½ days |
| 4 | [Backend: API-keys hardening — HMAC-of-full-key index prefilter (Fernet pepper), rotate-with-grace 24h + 3rd-rotation 409, `pk_live_`/`pk_test_` modes, separate rate buckets](step-4-api-keys-hardening.md) | Pending | ~1½ days |
| 5 | [Backend: `tbl_custom_events` + `tbl_custom_event_occurrences` (denormalised payload_schema_snapshot) + `_archive` (month-partitioned) + `tbl_custom_event_test_runs` (7d retention) + migration](step-5-custom-events-schema.md) | Pending | ~1 day |
| 6 | [Backend: `core/public_ingest/custom_events/` — CRUD with NFKC+ASCII name validation, reserved-name check, Owner-only edit/delete, `add_prefix` publish helper, single audit-history via `core/audit/`](step-6-custom-events-crud.md) | Pending | ~1 day |
| 7a | [Backend: `POST /events/track` auth pipeline — HMAC prefilter → Argon2id → HMAC verify (raw body, clock-skew, nonce) → idempotency (Redis, scoped `(org,key,idem)`) → rate limits (pre-auth IP, per-key, per-identifier)](step-7a-public-ingest-auth-pipeline.md) | Pending | ~1½ days |
| 7b | [Backend: `POST /events/track` payload + contact resolution — validator (types/caps/URL-scheme/enum/regex), contact_resolution via `contacts.service.create_contact_service()`, `default_owner_user_id` validation, uniform-response contact enumeration mitigation](step-7b-public-ingest-payload-contact.md) | Pending | ~1½ days |
| 7c | [Backend: `POST /events/track` bus publish + occurrence persistence + audit + response shaping + `pk_test_*` → `tbl_custom_event_test_runs` via dry-run](step-7c-public-ingest-publish-persist.md) | Pending | ~1 day |
| 8 | [Backend: bridges — `custom_events.service.list_catalog_for_org` (system + custom merge, `event_catalog` stays pure), workflow trigger picker wiring, variables registry payload-schema bridge](step-8-bridges-catalog-workflow-variables.md) | Pending | ~1 day |
| 9 | [Backend: workflow lifecycle — soft-delete auto-disables, re-activation prompt (excludes moved-trigger workflows), schema-removal review flag with re-scan on template save, extended contact-merge cascade to occurrences + `_archive`](step-9-workflow-lifecycle-and-cascade.md) | Pending | ~1 day |
| 10 | [Backend: Celery beat — occurrence archive job (90d, per-org iteration with `SET rls.org_id`), monthly partition rotation, `tbl_custom_event_test_runs` 7d cleanup, key-rotation 12h "still using old key" alert](step-10-retention-jobs.md) | Pending | ~1 day |
| 11 | [Frontend: `/user/settings/api-keys` (Owner-only) — list + create modal (default_owner picker, auto_create toggle, hmac_required toggle, live/test mode) + one-time reveal + rotate-with-grace countdown + copy-to-clipboard without visible plaintext](step-11-frontend-api-keys-page.md) | Pending | ~1½ days |
| 12 | [Frontend: `/user/settings/custom-events` list page — Admin+ view, Owner-only edit/delete affordances, "Custom events" grouping in trigger picker](step-12-frontend-custom-events-list.md) | Pending | ~½ day |
| 13 | [Frontend: create/edit modal — reuses shared schema-builder widget from Track A (VariableDef widget), reserved-name inline validation, live sample preview, allow test-fire from dirty form with "unsaved" banner](step-13-frontend-custom-events-modal.md) | Pending | ~1½ days |
| 14 | [Frontend: detail page — Overview + Occurrences (federated primary+archive when since>90d) + Test fires (from `_test_runs`) + Workflows using this (with re-enable prompt) + How to fire (in-session-only prefilled snippets; copy-to-clipboard without visible plaintext)](step-14-frontend-custom-events-detail.md) | Pending | ~1½ days |
| 15 | [Docs + smoke: OpenAPI events section + quickstart MD + Zapier walkthrough + contacts source-filter dropdown + reporting groupings updated for `event_ingest` + Ajay's Workspace end-to-end smoke](step-15-docs-and-smoke.md) | Pending | ~1 day |

**Total: 17 steps, ~19½ days** (Step 0 conditional on `dry_run.py` non-existence).

## Dependencies

- **`tasks/variables-unification/`** — soft. If shipped first, custom-event payload variables auto-propagate to every picker. If not, Step 8 patches only the workflow trigger picker; full picker coverage revisits post-Track A.
- **`core/events/bus`** — used to publish. ✓
- **`core/automation/event_catalog._CATALOG`** — read via service-layer merge; module stays pure. ✓
- **`core/workflows/`** — trigger dispatch + `dry_run` engine reused. ✓
- **`core/workflows/dry_run.py`** — test-fire runs through this. **Confirm exists in Step 7 kickoff; if not, sub-scope a "workflow dry-run engine" mini-track first.**
- **`core/embed/`** — moved under `core/public_ingest/embed/` in Step 2; existing keys keep working; `tbl_embed_keys` renamed to `tbl_api_keys` in Step 1.
- **`core/ai_assistants/public_context.py`** — moved under `core/public_ingest/ai_assistants/` in Step 2; endpoints unchanged.
- **`core/audit/`** — every key + event + workflow-lifecycle mutation emits an audit event.
- **Redis** — required for Step 3. Repo already uses Redis for Celery; confirm connection pool available for direct writes.
- **Celery Beat** — Steps 10 + 9. Already in place.

## File budget

| Area | Files |
|---|---|
| Step 1 | 1 migration (rename + add columns) + 1 modified embed models + 1 modified ai_assistants public_context + 1 modified embed router + 2 tests |
| Step 2 | New `core/public_ingest/{__init__, api_keys/, rate_limit/, idempotency/, hmac_verify/, embed/, ai_assistants/}/*` — bulk move + 3 `__init__.py` re-exports for backward-compat aliases + 2 tests |
| Step 3 | 3 new (`rate_limit/redis_store.py`, `idempotency/redis_store.py`, `hmac_verify/nonce_cache.py`) + 3 tests |
| Step 4 | 1 modified `api_keys/models.py` (`key_lookup_hash`, `old_key_hash`, `old_key_expires_at`, `mode`) + 1 migration + 1 modified `api_keys/service.py` + 4 tests |
| Step 5 | 1 migration + 3 new (`custom_events/models.py` — Event + SchemaVersion + Occurrence + Archive) + 1 test |
| Step 6 | 5 new (`schemas, router, service, data_access, versioning`) + 1 modified permissions registry + 4 tests |
| Step 7 | 3 new (`ingest/service.py, contact_resolution.py, payload_validator.py`) + 1 new `ingest/router.py` + 1 modified `main.py` + 8+ tests (sub-split to sub-steps 7a-7c during implementation if approaching Rule 8 limits) |
| Step 8 | 2 modified (`automation/service.py catalog_for_org`, `variables/service.py event_payload_bridge`) + 1 modified workflow trigger picker + 3 tests |
| Step 9 | 2 new (`custom_events/workflow_cascade.py`, `custom_events/schema_review.py`) + 1 modified `custom_events/service.py` + 1 modified `contacts/merge_service.py` (cascade list) + 3 tests |
| Step 10 | 2 new (`custom_events/archive_task.py`, `custom_events/schema_squash_task.py`) + 1 modified beat schedule + 2 tests |
| Step 11 | 5 new (list + create modal + reveal modal + rotate-with-grace UI + service) + 1 modified settings routes |
| Step 12 | 3 new (list + service + routes) |
| Step 13 | 5 new (modal + schema-builder-consumer + sample-preview + reserved-name validator + spec) — schema-builder itself imported from shared |
| Step 14 | 6 new (detail + 5 tabs + api service extension) |
| Step 15 | 2 new (quickstart MD + smoke script) + 1 modified OpenAPI tags |

**Total ~65 files across 15 steps. Step 7 is the risk (public ingest is the whole security perimeter) — sub-split to 7a/7b/7c if it approaches ~10 files / 400 lines.**

## Invariants this track enforces

| Rule | Where enforced |
|---|---|
| Public ingest API-key authed; no anonymous surface | Step 7 |
| API keys Argon2id at rest; secret shown once | Step 4 |
| HMAC-prefilter defeats Argon-DoS | Step 4 |
| Rotate-with-grace zero-downtime | Step 4 |
| `pk_test_*` events never fire real workflow actions | Steps 4 + 7 + `dry_run.py` |
| Redis-backed idempotency (multi-worker) | Step 3 |
| Redis-backed rate limits (multi-worker) | Step 3 |
| HMAC nonce cache (intra-window replay) | Step 3 |
| Uniform response for contact hit/miss (no enumeration) | Step 7 |
| Per-key stricter rate on `email`/`phone` lookup | Step 7 |
| Payload size cap 64KB + property regex + property count | Step 7 |
| `{{event.*}}` HTML-escaped by default; `|raw` opts in | Step 7 |
| Reserved names rejected | Step 6 |
| `custom.` prefix auto-injected | Step 6 |
| Custom event names unique per org (partial-index active only) | Step 5 |
| Payload schema versioned; occurrence renders with fire-time schema | Steps 5 + 6 + 8 |
| Soft-delete disables dependent workflows | Step 9 |
| Re-activation does NOT auto-re-enable workflows | Step 9 |
| Schema-key removal flags dependent workflows as "review needed" | Step 9 |
| Owner-only edit/delete/reactivate; Admin can create+view+test | Step 6 |
| Contact merge repoints occurrences | Step 9 |
| Contact delete nulls occurrence contact_id | Step 9 |
| Occurrences archived 90d → indexed RLS table | Step 10 |
| Every mutation emits audit event | Steps 4, 6, 7, 9 |
| Redis keys prefixed by `org_id` (no cross-org key pollution) | Step 3 |

## Self-check against the 10 rules

- **Rule 1** (core ↛ packs): pure core. ✓
- **Rule 2** (org_id + RLS): 4 new tables + 1 renamed — all `org_id NOT NULL FK` + RLS from migration one. ✓
- **Rule 3** (custom fields): unrelated storage-wise; UI schema-builder widget reused from Track A. ✓
- **Rule 4** (dynamic forms): payload-schema builder is itself a dynamic form. ✓
- **Rule 5** (sidebar registry): no new top-level sidebar entries — both pages under Settings.
- **Rule 6** (permission registry): 5 new permission keys — `api_keys.manage` (Owner), `custom_events.view` (Admin+), `custom_events.create` (Admin+), `custom_events.edit` (Owner), `custom_events.delete` (Owner).
- **Rule 7** (pack.yaml): N/A.
- **Rule 8** (step size): 15 steps; Step 7 flagged for sub-split. Otherwise all ≤ ~10 files. ✓
- **Rule 9** (stop-and-report): every step. ✓
- **Rule 10** (no TODOs): migration is complete in Step 1, not left half-done. GDPR payload PII scrub explicitly deferred to `gdpr-payload-scrub` follow-up track (not left as a TODO in code). ✓

## After this track

- Any external system (Shopify webhook, Stripe webhook, Zapier zap, Make scenario, custom backend cURL) can fire events into the CRM in minutes.
- Workflows fire on custom events; templates render `{{event.<key>}}` merged from payload.
- Combined with `tasks/variables-unification/`, custom events auto-populate every picker.
- Public tracking API opens the door to first-party Zapier/Make/n8n apps + browser JS SDK (future GTM tracks).
- `public_ingest` module becomes the one place any future public-authenticated surface (webhook receivers, SMS-inbound endpoints, external forms) plugs into for auth + rate + audit + HMAC.
