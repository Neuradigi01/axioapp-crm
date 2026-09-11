# Variables Unification — one registry for every template / workflow / chatbot / automation-condition picker

**Promote `core/templates/variables.py` (already the shared parser + renderer + registry, 413 lines) to `core/variables/`, point every picker at it, and back the picker on the frontend with one Angular component.** Templates editor, Workflows action config, Workflows condition builder, Chatbots node palette, Automation event-conditions builder, and every future surface (Campaigns, AI-assistant prompts, PDFs, push, SMS) consume the same endpoint and render through the same component. Custom fields — and, once `tasks/custom-events/` ships, custom-event payloads — automatically propagate everywhere.

## Why this track exists (revised after audit 2026-09-11)

The original diagnosis was three inconsistent pickers. The real state is worse: **four** picker/registry sources, one of which is already ~5× more thorough than the others and is used by the render pipeline downstream — but the three other surfaces bypass it and reinvent partial versions.

| Surface | Picker source | Uses the shared renderer? | Uses custom fields? |
|---|---|---|---|
| **Templates** editor (`app/.../templates/editor/variable-picker.component.ts`) | Backend `GET /templates/variables/{channel}` — served by `TemplatesApiService.variables()` reading `ALLOWED_VARIABLES_BY_CHANNEL` in `core/templates/variables.py` | ✓ `templates/variables.render` | **No** |
| **Workflows** editor (`app/.../workflows/canvas/variable-picker.component.ts`) | 100% hardcoded TS `VARIABLE_GROUPS_BY_EVENT_PREFIX` at `editor-contract.ts:238` | ✓ (workflow action files import `templates.variables.resolve as render` — send.py:293, flow_control.py:295, tagging.py:55, records.py:91) — **the renderer is already shared, only the picker isn't** | **No** |
| **Chatbots** editor (`app/.../shared/variable-picker/variable-picker-api.service.ts`) | Backend `GET /chatbots/variables` — served by `core/chatbots/variables.list_variables()` | ✗ Chatbots uses `channel_bridge.render_variables` (separate) | ✓ |
| **Automation Conditions** builder (`app/.../automation/conditions/...`) | Backend `GET /automations/event-types` — served by `automation/service.list_event_types_with_custom_fields()` reading `event_catalog._CATALOG[event].condition_fields` (`FieldSpec` shape) | N/A (conditions are filters, not renders) | ✓ (already batches `list_fields_by_entities`) |

Three of these compose `system + custom-fields` independently, with **three different data shapes**: `VariableDef` (templates), `Variable` (chatbots), `FieldSpec` (automation). Custom-field composition is duplicated in three places. The reference implementation for merging is not chatbots — it is the templates module, which already ships the parser (`extract_variable_paths`), the strict + lenient renderers (`render` / `resolve`), and per-entity variable tuples for **all 8 entities** the audit named (`_CONTACT_VARS / _ORG_VARS / _SENDER_VARS / _LEAD_VARS / _USER_VARS / _APPOINTMENT_VARS / _QUOTE_VARS / _INVOICE_VARS`).

**Client complaints (2026-09-11)** — "chatbots palette is smaller than templates; workflows won't let me insert `{{contact.custom.vip_status}}`; I have to type merge tokens by hand" — are all downstream symptoms of the same cause: three pickers reinvent what `core/templates/variables.py` already declares.

## What changes

- **Promote (move, not clone)** `core/templates/variables.py` → `core/variables/` — a Router → Service → DAL module. Preserve every export (`extract_variable_paths`, `reject_jinja_statements`, `render`, `resolve`, `ALLOWED_VARIABLES_BY_CHANNEL`, `_CONTACT_VARS`, `VariableDef`). Every existing import site (templates service, workflow action files, automation renderer) is re-pointed. **Renderer stays co-located with parser and registry — this is a strength; splitting them would be the mistake.**
- **One data shape.** `VariableDef` (templates) + `Variable` (chatbots) + `FieldSpec` (automation) fold into a single `VariableDef` in `core/variables/schemas.py`. Superset fields: `path, label, type, group, sample, default, required, description, help_text, enum_resolver`. Existing callers are adapted; no behavior loss (templates' `type=currency/date` preserved; chatbots' `sample/description` preserved; automation's `enum_resolver/help_text` preserved).
- **Extend `automation/custom_field_bridge.to_field_spec`, don't clone it.** Chatbots' private `_custom_field_variables` and automation's private path both delegate to the same bridge function. One place to fix custom-field composition.
- **Unified endpoint.** `GET /api/v1/variables?entity=<name>&channel=<name>&event=<name>` returns `{ groups: [{ key, label, variables: [VariableDef, ...] }, ...] }`. Read `org_id` from `TenantContextMiddleware`; **`list_fields_by_entities(org_id: UUID, ...)` gains `org_id` as a REQUIRED kwarg** (belt-and-suspenders; existing callers in `automation/service.list_event_types_with_custom_fields` audited and updated in Step 3 — type-checker enforces no forgotten arg). Response includes `Cache-Control: private, max-age=60` + ETag; hard-cap response `variables[]` at 500 with `truncated: true` flag; per-user rate limit 60 rps.
- **Composer-permission dispatch (revised after review).** Field-schema labels are not PII; benchmark check confirms HubSpot / Salesforce / Zoho all gate merge-field pickers on **composer permissions** (edit-template / edit-workflow / edit-chatbot / edit-campaign), NOT per-object read permissions. Our endpoint gates on **any of** `templates.edit`, `workflows.edit`, `chatbots.edit`, `campaigns.edit`, `automations.edit`, `ai_assistants.edit` — union of "user who can compose". Additionally, per-entity gate on data-sensitive fields is deferred: **standard variable metadata (labels/types) is visible to any composer**; **custom-field descriptions marked `is_sensitive=true` in `tbl_custom_field_definitions`** are gated on the entity's per-object read perm (new column added in Step 3, defaults false). Fixes: (a) closes today's `get_current_user`-only gap for any-authenticated-user access, (b) doesn't break the "Employee composing lead-followup workflow needs to insert `{{invoice.total}}` reference in an internal note" case that per-entity gating would break, (c) explicit opt-in for orgs that need stricter gating on sensitive-labelled fields. Actual perm-key strings (`contacts.read`, not `PERM_CONTACTS_VIEW`) verified against `core/permissions/` at Step 4 implementation.
- **Pack-event visibility respected.** When merging `{{event.*}}` groups, `event_catalog.is_visible_to(entry, caller_org.template_id)` filters out pack events that the caller's org hasn't installed. No pack schema leak.
- **`{{event.*}}` namespace corrected.** Publishers emit payload flat under entity keys (`contact.first_name`, `lead.pipeline_stage`) — those already resolve via the existing renderer. The `{{event.*}}` group is reserved for **trigger-specific fields not on any entity** (e.g. `event.from_stage_id` / `event.to_stage_id` for `lead.status_changed`). No double-definition.
- **Fourth surface migrated.** Automation Conditions builder switches from `/automations/event-types` composition-in-service to the shared registry. That endpoint remains as a *view* over the shared catalog (its response layers `condition_fields` restricted to filterable variables on top of `variables`), but no longer batch-loads custom fields itself. Kills a fourth registry.
- **Shared Angular component — reuse existing `shared/variable-picker/`, don't clone.** The chatbots picker at `app/src/app/features/user/core/shared/variable-picker/variable-picker.component.ts` IS already the shared home (currently chatbots-only). Step 7a generalises it in place (keeps the directory name, extends the component + service to support `entity`/`channel`/`event` inputs), rather than creating a parallel `shared/variables/` directory. Preserves git history + import paths for chatbots.
  - `variable-registry.service.ts` (extended from existing `variable-picker-api.service.ts`) — cache keyed by `(org_id, user_permission_hash, entity, channel, event)`. **`org_id` defeats org-switcher leaks; `user_permission_hash` invalidates on role changes** (avoids the "revoked user still sees cached fields for 5 min" bug). 5-minute TTL from last-access.
  - **Cross-tab invalidation via `BroadcastChannel('crm-variable-registry')` — payload is opaque `{ org_id, generation }` only, NOT field paths/labels.** Receiver bumps its cache generation and refetches if org_id matches its current session. No field path metadata leaks on shared browsers. Fallback for browsers without BroadcastChannel (older Safari private mode): TTL-only (documented).
  - Component supports insertion into `<input>` / `<textarea>` (Templates subject line, Workflows recipient email, Task title, Tag name, Send-Email cc/bcc) as well as `contenteditable` (Templates body, Chatbot Ask prompt). **Type-ahead search** input at top (HubSpot parity — non-negotiable at 100+ fields), **recently-used group** pinned to top per surface (client-side, localStorage keyed by user+surface — HubSpot parity), and **fallback-value input prompt at insertion time** (`{{contact.first_name | default:"there"}}` — HubSpot/Zoho parity).
- **Stale-reference reverse index.** When a custom field is deleted OR renamed, `core/custom_fields/service.py` publishes `custom_field.deleted` / `custom_field.renamed` on the internal bus; a subscriber (Celery task, per-org scoped with explicit `org_id` filter — NOT RLS-only) walks the actual reference surfaces:
  - `tbl_message_templates.body_text` + `tbl_message_templates.subject` + `tbl_message_templates.preview_text`
  - `tbl_workflow_versions.graph` JSONB (workflow node configs are versioned blobs, NOT a `_nodes` table)
  - `tbl_chatbot_versions.graph` JSONB (same)
  - `tbl_campaigns.body_text` + `tbl_campaigns.subject` (Campaigns v1 = WhatsApp + Email per project memory)
  - `tbl_automation_actions.config` JSONB (automation action templates that may override with `{{...}}`)
  
  Writes rows to `tbl_variable_stale_refs (id, org_id, source_entity_type, source_id, path, reason [deleted|renamed|type_changed], detected_at, resolved_at NULLABLE)` with `UNIQUE (org_id, source_entity_type, source_id, path)` — no duplicates on repeated mutations. Owner sees a "Stale variable references" pane in Settings; endpoint `POST /variables/stale-refs/{id}/resolve` dismisses a row (creating an audit event). Auto-resolves when the referring template body/config is edited to remove the reference (subscriber re-walks on `template.saved` / `workflow.saved` / `chatbot.saved`). Cascade on referring row delete = CASCADE via source-type-aware trigger, not a polymorphic FK. **Bulk delete guard:** if >100 field deletions from one org within 60s, subscriber batches into one scan pass per surface (not N scans) and rate-limits alerts.
- **Config-inputs support.** The picker component supports insertion into `<input>` / `<textarea>` (Templates subject line, Workflows recipient email, Task title, Tag name, Send-Email cc/bcc) as well as `contenteditable` (Templates body, Chatbot Ask prompt). Both cursor positions handled by the shared component.
- **Default-value + sample.** Every `VariableDef` carries an optional `default` (fallback rendered when the path resolves to empty) and a `sample` (used by the "Preview" pane). Templates' existing `default` semantics preserved. Matches HubSpot / Zoho parity.
- **CI pin-test — structural, not heuristic.** `API/tests/test_shared_variable_picker_only.py` fails CI if any Angular component under `APP/src/app/features/user/core/**` is named `*variable-picker*` **and** lives outside `APP/src/app/features/user/core/shared/variables/`. Grep is unambiguous — no counting literals, no false positives on entity-namespaced pickers.

## What this track does NOT include

- **Runtime resolver coverage for chatbots' aspirational `lead.*` scope.** Chatbots today surfaces `lead.status`, `lead.source`, `lead.won_value` in the picker but its runtime resolver (`channel_bridge.render_variables`) doesn't know how to walk them (see `chatbots/variables.py` module docstring). This track surfaces the same variables from the unified registry but the picker adds a **"not resolvable in this context" badge** on paths whose runtime-resolver returns null-sentinels. Full runtime coverage is a follow-up track (`chatbot-runtime-resolver-coverage`) — noted, not built.
- **Multi-language / i18n labels.** English-only, matching rest of app.
- **Real-time WebSocket cache invalidation across users.** HubSpot does this; we ship BroadcastChannel (cross-tab, same browser) + 5-min TTL. Cross-user real-time is a bigger track.
- **Variable-to-field-definition click-through.** Nice-to-have, not needed for parity. Deferred.
- **The custom-events feature itself.** See `tasks/custom-events/`. This track defines the `{{event.*}}` **contract** and the `custom_events.payload_schema` bridge point so Custom Events plugs in when it ships.
- **Renderer changes.** The renderer is already shared; this track doesn't rewrite it. If a variable is in the picker, the renderer can already resolve it (or renders empty, matching current behavior).

## Multi-tenancy

- No new tenant tables. Reuses `tbl_custom_field_definitions` (already `org_id` scoped, RLS enforced).
- One new **advisory** table `tbl_variable_stale_refs` — `org_id NOT NULL FK + RLS from migration one`.
- `GET /variables` reads `org_id` from `TenantContextMiddleware`. Explicit `WHERE org_id = ?` in every DAL query (belt) + RLS (suspenders). Regression test patches out the RLS hook and asserts the explicit filter still enforces isolation.
- Frontend `VariableRegistryService` cache keyed by `(org_id, entity, channel, event)`. Org-switcher hooks emit `org.switched` on the client bus → registry clears its cache. Cross-tab `BroadcastChannel` also carries the org_id in the invalidation message.

## Locked design choices (won't relitigate during implementation)

| Decision | Why | Comparison |
|---|---|---|
| **Promote (move) `templates/variables.py` → `core/variables/`, don't parallel-build** | The shared registry already exists and is 5× more complete than any picker-only alternative. Building alongside creates two definitions of `_LEAD_VARS`, guaranteed to drift. | HubSpot's `PersonalizationDropdown` shares state with the send-time renderer. Same principle. |
| **One shape (`VariableDef` superset), not three (VariableDef / Variable / FieldSpec)** | Three shapes = three edit surfaces on every change. Superset means every field a caller might need is available; unused fields are optional. | HubSpot / Salesforce merge-field APIs return one shape per property. |
| **Endpoint permission is per-entity, not bare authed** | An Employee restricted to Chatbots must not enumerate Invoice custom-field labels — those often contain PII / internal terms. | Salesforce Field Metadata API filters by object-level FLS. |
| **Explicit `org_id` filter in DAL, not RLS-only** | RLS is one bug (a wrong `SET LOCAL app.org_id` in any code path, a Celery worker missing the ContextVar) away from cross-tenant leak. Belt-and-suspenders. The existing chatbots reference (`list_visible_custom_fields_for_org`) already does this. | Standard defense-in-depth. |
| **Provider-duplicate at registration → env-gated: raise in `dev`/`test`/`ci`, log + first-wins in `prod`** | Dev/CI catches merge conflicts (real bugs) loudly; prod avoids full-app boot DoS on genuine merge-collision hitting production. Core providers register into `core:<name>` namespace; pack providers (future Layer 2) register into `pack:<pack_id>:<name>` — cross-namespace collisions structurally impossible. | Existing `event_catalog._register` pattern extended. |
| **Cache key includes `org_id`** | Multi-org users switching orgs in-tab must not see org A's fields in org B's picker. | Standard tenant-scoped cache. |
| **Cross-tab invalidation via `BroadcastChannel`, cross-user via 5-min TTL** | WebSocket for real-time cross-user invalidation is a much bigger track. TTL + BroadcastChannel covers the 95% case. | Notion / Linear use BroadcastChannel for cross-tab; live-collab is a separate infra concern. |
| **`{{event.*}}` reserved for trigger-specific fields NOT on entities** (`event.from_stage_id`, not `event.first_name`) | Publishers emit payload flat under entity keys (`contact.first_name`) — those already resolve. `event.first_name` would double-define. `event.*` is for stuff like transition fields. | Matches how `event_catalog.condition_fields` uses `GROUP_TRANSITION` today. |
| **Pack-event visibility filtered via `is_visible_to()`** | Otherwise pack-scoped events leak schema keys to orgs that haven't installed the pack. | Automation `/event-types` endpoint already applies this filter; we adopt it. |
| **Stale-reference detection on custom-field delete → advisory row, not auto-cleanup** | Auto-editing template bodies is scary and irreversible. Surface the problem, let Owner decide. Same pattern as workflow "issues" pane in HubSpot. | HubSpot Workflow Issues pane. |
| **Pin-test: name-based, not heuristic** | Grep for `*variable-picker*` file names outside `shared/variables/`. Unambiguous, no false positives on entity-namespaced pickers. | Repo already has structural pin-tests (`tbl_`, DAL layering). |
| **Deprecation windows carry a calendar + owner** | Rule 10 forbids "I'll fix it later." Endpoints scheduled for removal have a target release ID in the code comment + a tracking row in `tasks/variables-unification/deprecations.md`. | Every serious repo. |
| **Default-value + sample fields on VariableDef** | HubSpot + Zoho pickers both show a default-value input at insertion time and a sample-value preview. Skipping this is an accidental regression. | HubSpot Personalization Tokens, Zoho Merge Fields. |
| **Config-input support (input/textarea + contenteditable)** | Templates subject, recipient email, task title, tag name are all inputs — same picker must work there. | Notion `/` menu works in any editable surface. |

## Absence (what the plan explicitly names)

- **Two-user race — User A opens picker, User B creates a custom field in same org:** BroadcastChannel emits `custom-field-created` to all tabs of both users' browsers if both sessions are open in the same browser. Cross-browser: TTL (5 min) covers. Server has no server-side cache.
- **Two-user race — User A opens picker, User B deletes a custom field User A is about to insert:** Picker refreshes via BroadcastChannel/TTL. If User A already inserted `{{contact.custom.vip}}` and User B deletes `vip` after, the stale-reference detector writes a row; the template still renders empty (existing behavior). Owner sees the stale ref in Settings.
- **Custom field deleted, then re-created with same key for a different purpose:** Old templates now render the new value. Stale-reference detector fires on delete AND on create-with-same-key; Owner sees a warning "path `contact.custom.vip` is referenced in 47 templates; the field was recently deleted and re-created — verify meanings."
- **Two API workers, different provider registrations:** Providers are static core code loaded at import — the same set in every worker (API + Celery + beat). Test asserts `_PROVIDER_REGISTRY` keys are identical after boot across pytest fixtures simulating each worker type.
- **Chatbots feature disabled per-org:** `chatbot_runtime` entity provider consults `org.chatbots_enabled` before returning; endpoint returns 403 on that entity for disabled orgs.
- **Renderer coverage vs picker coverage:** paths surfaced in the picker but not resolved by any publisher render empty (matches current behavior for `contact.middle_name` etc.). Picker adds `is_resolvable_here: bool` in the response per path per surface; UI shows a "not available in this context" badge on false.
- **Org deleted:** custom-field cascade + stale-refs cascade; picker cache clears via `org.switched` bus signal.
- **Provider registration duplicate:** log warning, first-wins.
- **Endpoint called for unknown entity:** 400 with `known` filtered by caller-visible entities (permission-oracle-safe).
- **Endpoint called with `event=<unknown>`:** silently drops event group; logs at INFO level (not warn — a stale frontend build shouldn't spam alerts). Returns other groups.
- **Endpoint called by unauthenticated caller:** 401.
- **Cross-tenant custom-field guess:** explicit `org_id` filter + RLS return empty; verified by test with RLS patched out.
- **`chatbot_runtime` entity's user-facing exposure:** intentional (users composing chatbot flows need it); documented; per-entity permission gate matches "chatbot access."
- **Deprecation calendar:** Step 10 defines the release train — `/templates/variables/{channel}` removed in the next release after Step 10 lands (target N+1); `/chatbots/variables` in N+2. Owners named in the deprecations MD.

## Cases

| Case | Behavior |
|---|---|
| User in org A + user in org B both hit `GET /variables?entity=contact` | Each sees only their org's custom fields (explicit filter). |
| User A logged into orgs A+B, switches from A to B mid-session | Cache-key includes `org_id`; switch fires `org.switched` → cache clears. |
| User A opens 3 tabs, custom field added in tab 1 | Tab 1 emits `custom-field-mutated` on same-tab bus; `BroadcastChannel` also fires → tabs 2 + 3 clear cache. |
| Employee restricted to Chatbots calls `GET /variables?entity=invoice` | 403 (missing `invoices.view`). |
| Provider file duplicated by merge | Log warning at boot; first-wins; API stays up. |
| Custom field deleted while templates reference it | Body unchanged; renderer returns empty; stale-ref row written for Owner's visibility. |
| Custom field re-created with same key | Stale-ref detector fires again on create; Owner warned "recently deleted + re-created." |
| Sample payload key added to a system event's `_CATALOG` entry | Registry surfaces the new key next request; no cache invalidation needed server-side (per-request read). |
| `{{event.*}}` requested for pack-scoped event on non-installer org | Event group silently omitted (via `is_visible_to`). |
| Endpoint hit with `?event=nonexistent` | Other groups returned; INFO log server-side. |
| Cross-tenant `entity=contact` custom-field IDs guessed | Empty set (RLS + explicit filter). |

## Tests (named before code exists)

**Backend:**
- `test_variables_endpoint_returns_system_only_without_event` — `?entity=contact&channel=email` returns Contact + Contact-custom groups; no `event.*`.
- `test_variables_endpoint_appends_event_payload_only_when_event_passed` — `&event=lead.status_changed` appends `event.*` with transition-only keys, NOT entity-payload duplicates.
- `test_variables_endpoint_includes_org_custom_fields_via_explicit_filter` — seed field in org A → appears for A; **RLS hook mocked off** and cross-tenant still returns empty (belt works without suspenders).
- `test_variables_endpoint_403_on_missing_entity_permission` — Employee w/o `invoices.view` hits `entity=invoice` → 403.
- `test_variables_endpoint_400_on_unknown_entity_filters_known_by_perm` — 400's `known` list contains only entities the caller can read (permission-oracle-safe).
- `test_variables_endpoint_ignores_unknown_event_gracefully` — INFO logged; other groups returned.
- `test_variables_endpoint_pack_event_hidden_for_non_installer_org` — pack `furniture.*` event with sample_payload → org without pack sees no `event.*` keys.
- `test_provider_registration_duplicate_logs_and_first_wins` — no raise; log captured.
- `test_provider_registry_identical_across_worker_types` — API + Celery + beat load same providers.
- `test_workflow_action_files_import_from_core_variables` — pin-test asserts `send.py`/`flow_control.py`/`tagging.py`/`records.py` no longer import from `core.templates.variables` after promotion.
- `test_stale_reference_row_written_on_custom_field_delete` — delete field; row appears in `tbl_variable_stale_refs`.
- `test_stale_reference_row_written_on_recreate_with_same_key` — delete + create with same key; second row appears.
- `test_variable_def_unified_shape_supports_all_existing_callers` — round-trip templates' `type=currency`, chatbots' `sample`, automation's `enum_resolver`.
- `test_no_hardcoded_variable_pickers_pin` — name-based scan; passes today; fails on any new `*variable-picker*` file outside `shared/variables/`.

**Frontend:**
- Playwright: **templates editor** picker inserts at cursor (subject input + body contenteditable).
- Playwright: **workflows editor** picker inserts on action-config inputs AND on condition builder.
- Playwright: **chatbots editor** picker still works after migration.
- Playwright: **automation conditions builder** switches to new shape; existing saved conditions still render.
- Playwright: **org switcher** clears picker cache — org A field not visible after switch to org B.
- Playwright: **multi-tab invalidation** — create field in tab 1, tab 2 sees it without reload.
- Playwright: **"not resolvable here" badge** — chatbot picker shows badge on `lead.status`.

## Theme groupings

| Theme | Steps | Why grouped |
|---|---|---|
| Promotion + shape unification | 1-3 | Move `templates/variables.py` → `core/variables/`; unify VariableDef; extend custom_field_bridge |
| Endpoint + security | 4-5 | Unified `GET /variables` with per-entity perms, explicit org_id filter, pack visibility |
| Registry integrations | 6 | Fold automation `/event-types` composition into shared catalog; stale-ref detector |
| Shared frontend component | 7 | `<crm-variable-picker>` + `VariableRegistryService` |
| Surface migrations | 8-10 | Templates → Workflows → Chatbots+Automation |
| Cleanup + pin-test + smoke | 11 | Deprecation calendar, name-based pin-test, smoke against Ajay's Workspace |

## Steps index

| # | Title | Status | Effort |
|---|---|---|---|
| 1 | [Backend: promote `core/templates/variables.py` → `core/variables/` (module skeleton + import repointing)](step-1-promote-variables-module.md) | Pending | ~1 day |
| 2 | [Backend: unify `VariableDef` shape (fold `Variable` + `FieldSpec`) + adapter shims for existing callers](step-2-unify-variable-shape.md) | Pending | ~1 day |
| 3 | [Backend: extend `custom_field_bridge` + `list_fields_by_entities(org_id)` for explicit tenant filter](step-3-extend-custom-field-bridge.md) | Pending | ~½ day |
| 4 | [Backend: `GET /api/v1/variables` router with per-entity permission dispatch](step-4-unified-router-perms.md) | Pending | ~1 day |
| 5 | [Backend: `{{event.*}}` handling (transition-only keys) + `is_visible_to` pack filtering](step-5-event-namespace-and-pack-visibility.md) | Pending | ~½ day |
| 6 | [Backend: `tbl_variable_stale_refs` table + custom-field delete/recreate subscriber](step-6-stale-reference-detector.md) | Pending | ~1 day |
| 7a | [Frontend: generalise existing `shared/variable-picker/` component (input+textarea+contenteditable; search; recently-used; fallback-at-insertion)](step-7a-frontend-shared-picker-component.md) | Pending | ~1½ days |
| 7b | [Frontend: `VariableRegistryService` (cache key + user_permission_hash + BroadcastChannel opaque payload + org.switched wiring)](step-7b-frontend-registry-service.md) | Pending | ~1 day |
| 8 | [Frontend: migrate Templates editor to shared picker (subject input + body contenteditable + preview-text)](step-8-frontend-migrate-templates.md) | Pending | ~½ day |
| 9 | [Frontend: migrate Workflows editor (action-config inputs + condition builder) + delete hardcoded map](step-9-frontend-migrate-workflows.md) | Pending | ~1 day |
| 10a | [Frontend: migrate Chatbots editor to shared picker (data-source swap only; add "not resolvable here" badge)](step-10a-frontend-migrate-chatbots.md) | Pending | ~½ day |
| 10b | [Frontend: migrate Automation Conditions builder + `/automations/event-types` becomes a view over shared catalog](step-10b-frontend-migrate-automation-conditions.md) | Pending | ~1 day |
| 11 | [Cleanup: name-based CI pin-test + deprecation calendar (with removal-target dates, not release-train IDs) + Ajay's Workspace smoke](step-11-cleanup-pintest-smoke.md) | Pending | ~½ day |

**Total: 13 steps, ~10½ days.** Each step ≤ ~10 files / ~400 lines per Rule 8.

## Dependencies

- `core/templates/variables.py` — exists (the whole track hinges on promoting it).
- `core/custom_fields/data_access.py` — extended in Step 3 to accept `org_id` as an explicit filter.
- `core/automation/custom_field_bridge.py` — extended in Step 3 (add-only; no breaking change to existing `to_field_spec` / `mounts_for`).
- `core/automation/event_catalog.py` — read for `sample_payload` + `condition_fields`; visibility filter reused.
- `core/events/bus` — used by stale-ref detector.
- `core/audit/` — every stale-ref insert emits an audit event.
- `tasks/custom-events/` — **not a hard dependency.** This track ships useful on its own; Custom Events plugs into the `event=<name>` slot once its schema exposes `payload_schema` (Step 5 of that track).

## File budget

| Area | Files |
|---|---|
| Step 1 | 6 new (`core/variables/{__init__,router,service,data_access,schemas,models}.py` — some empty stubs) + 4-6 modified (import repointing across templates, workflows/actions, automation) + 1 modified `main.py` |
| Step 2 | 1 modified `schemas.py` + adapter helpers + 2 modified `automation/field_specs.py` / `chatbots/variables.py` |
| Step 3 | 1 modified `custom_fields/data_access.py` + 1 modified `custom_field_bridge.py` + 1 test |
| Step 4 | 1 modified `router.py` + 1 modified `service.py` + `_ENTITY_READ_PERM` map + 3 tests |
| Step 5 | 1 modified `service.py` + tests |
| Step 6 | 1 migration + 1 new `models.py` (StaleRef) + 1 new `stale_ref_detector.py` + 1 modified `custom_fields/service.py` (publishes delete event) + 2 tests |
| Step 7 | 3 new (`variable-picker.component.ts/.html`, `variable-registry.service.ts`) + 1 spec |
| Step 8 | 1 modified templates editor picker + 1 template body |
| Step 9 | 1 modified workflows canvas picker + 1 deletion of hardcoded map + 1 wiring in condition-builder |
| Step 10 | 1 modified chatbots picker + 1 modified automation conditions picker + 1 badge component |
| Step 11 | 1 new pin-test + 1 new `deprecations.md` + smoke script |

**Total ~30 files across 11 steps.**

## Invariants this track enforces

| Rule | Where enforced |
|---|---|
| Only ONE variable picker component exists in `APP/src` (`shared/variables/variable-picker.component.ts`) | Name-based pin-test (Step 11) |
| ONE registry (`core/variables/`) — no `_LEAD_VARS`/`_CONTACT_VARS` outside it | Import pin-test (Step 1) |
| Every endpoint read filters by `org_id` explicitly + RLS | Regression test with RLS patched off (Step 4) |
| Per-entity read permission enforced on `/variables` | Test in Step 4 |
| Cache keyed by `org_id` client-side | Playwright org-switch test (Step 7) |
| Pack events invisible to non-installer orgs | Test in Step 5 |
| Stale references surfaced to Owner on custom-field delete | Test in Step 6 |
| Config inputs + contenteditable both supported | Playwright tests (Step 7) |
| Deprecation windows have calendar + owner | `tasks/variables-unification/deprecations.md` (Step 11) |

## Self-check against the 10 rules

- **Rule 1** (core ↛ packs): pure core. ✓
- **Rule 2** (org_id + RLS): one new table `tbl_variable_stale_refs` with `org_id NOT NULL FK + RLS from migration one`. Existing `tbl_custom_field_definitions` untouched. ✓
- **Rule 3** (custom fields layered): consumes; doesn't modify. ✓
- **Rule 4** (dynamic forms): N/A — picker is picker, not form.
- **Rule 5** (sidebar registry): N/A.
- **Rule 6** (permission registry): reuses per-entity read perms; no new perm keys. ✓
- **Rule 7** (pack.yaml): unaffected. ✓
- **Rule 8** (step size): 11 steps, largest ~10 files. ✓
- **Rule 9** (stop-and-report): every step. ✓
- **Rule 10** (no TODOs): retirements happen in Step 11 with calendar; no lingering half-done. ✓

## After this track

- Every future picker surface (Campaigns editor, AI-assistant prompts, PDF templates, SMS bodies, push text) drops in for free.
- `tasks/custom-events/` inherits `{{event.*}}` propagation across all four surfaces without extra picker code.
- The class of client complaint "variable X is available in Y but not Z" cannot recur — enforced by CI, not by convention.
- Custom-field lifecycle is safer: delete/recreate surfaces to Owner rather than silently changing template outputs.
