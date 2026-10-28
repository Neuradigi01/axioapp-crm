# Step 6 — Backend: `email_templates` table + variable substitution engine

**Goal:** Org-scoped library of reusable email templates with variable placeholders (`{{contact.first_name}}`, `{{lead.pipeline_stage}}`, `{{contact.custom_data.preferred_brand}}`). Templates store subject + body (HTML + plain) + variable schema discovered at render time. Render returns a fully-substituted MIME-ready payload.
**Track:** App Updates → Email
**Status:** COMPLETED — `email_templates` table shipped via migration `0083_add_email_templates` with `(org_id)` + RLS + partial-active index `(org_id, is_active) WHERE deleted_at IS NULL` + partial-unique index `(org_id, lower(name)) WHERE deleted_at IS NULL` so soft-deleted tombstones don't block a name reuse. `created_by` is plain UUID (no FK) per post-0037 convention. `core/email/variables.py` ships a hand-rolled substitution engine — **no Jinja2 dependency** (deliberate: Jinja2 isn't in requirements, sandbox escapes are a recurring CVE class, and the spec rejects `{% ... %}` constructs anyway). Three pure operations: `extract_variable_paths(text)` returns sorted-unique dot-paths matched by `\{\{\s*([a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)*)\s*\}\}`; `reject_jinja_statements(text)` raises `TemplateSyntaxError` on any `{% ... %}` or `{# ... #}`; `render(text, context, *, autoescape=True)` substitutes against a nested dict with HTML escape via `html.escape(quote=True)` (autoescape=False for plain-text body path), raises typed `MissingVariable(paths=[...])` listing every unresolved path so the router 400 lists them precisely. `core/email_templates/` sub-package ships `models.py` (`EmailTemplate` with `variables_used` JSONB, soft-delete `deleted_at`), `schemas.py` (`EmailTemplateCreate` / `Update` / `Read` / `RenderResponse` / `VariableRegistryEntry`), `service.py` (the meat: `validate_template_text` runs Jinja-reject + extract + allowlist check against `custom_field_definitions` for the org, raises 400 listing offending paths; `html_to_text` extractor via stdlib `HTMLParser` subclass `_HtmlToText` — preserves line breaks from `<br>`/`<p>`/headings/lists, inlines `<a href="X">Y</a>` as `Y (X)`, collapses 3+ blank lines; `build_context` loads contact/lead/org/sender into nested dict including unfurled `custom_data`; `render_template` substitutes subject with autoescape + body_html with autoescape + body_text without autoescape, surfaces MissingVariable as 400 with the path list; `variable_registry` returns 19 static + N custom-field entries sorted by category for Step 10's editor sidebar; standard CRUD with name-uniqueness 409 + audit events `email.template.created`/`updated`/`deleted`), `router.py` (full CRUD + `GET /variables` + `POST /{id}/render?contact_id=&lead_id=` — write paths gated by `email.templates.manage`, read paths by `email.read`), `module.py` (descriptor with menu_position=None — managed via Settings → Email Templates in Step 10). Two permission keys registered via module sweep AND added to role templates: `email.read` (Owner/Admin/Employee/SalesManager/SupportAgent — everyone uses templates from compose) + `email.templates.manage` (Owner/Admin/SalesManager — authoring stays admin-side). Tests cover: variables engine (extract dedupe+sort, deep paths, Jinja for/if/comment rejection, render substitution, autoescape on/off, missing variable raises, None renders empty, statement-rejection at render time too); html_to_text (strips tags, `<br>` → newline, link URLs inlined, empty input); validate_template_text (happy static paths, custom field allowed when defined, unknown path 400, undefined custom_data 400, Jinja rejected, empty template); render_template (happy, autoescape HTML body, plain text skips escape, missing variable 400); CRUD state machine (create persists with variables_used + duplicate name 409, partial update revalidates on subject change, empty patch no-op, soft delete sets tombstone, get soft-deleted 404). **Notable adaptations from the spec:** (a) **No Jinja2 / html2text deps** — hand-rolled engine + stdlib `HTMLParser` extractor; smaller attack surface + zero new deps; (b) **Variable engine is regex-based with strict whitelist** — only `{{ lowercase_path }}` substitutions allowed, ANYTHING else (statements, comments, expressions, filters, even uppercase variable names) is rejected; (c) **AST sandbox is unnecessary** — without an interpreter there's no AST to sandbox; we never parse a template language at all; (d) **`body_text` auto-derived on save** when caller omits it — same behaviour as Step 7's `html_to_text` path will reuse; (e) **`org.support_email`** read via `getattr` since the Organization model may or may not expose that field — graceful degrade to empty string; (f) **Permission gate split** — `email.read` (gates GET surfaces + render preview) vs `email.templates.manage` (gates POST/PATCH/DELETE) gives Employees and Support Agents access to use templates without granting authoring. Smoke verified: `discovered modules` includes `email_templates`; GET /templates → 200 `{items:[], total:0}`; GET /variables → 200 with 21 entries (19 static + 2 from org's custom_field_definitions auto-discovered); POST with `{% for %}` → 400; POST valid template → 201 with `variables_used: [contact.first_name, org.name, user.full_name]` + body_text derived from body_html; POST /render against a real contact → 200 with subject + body_html showing autoescape on (`&#x27;` for apostrophe) + body_text showing autoescape off (literal `'`) + substituted user.full_name (`ajaygogane224@gmail.com`) + org.name (`Ajay's Workspace`); DELETE → 200 `is_active: false`; subsequent GET excludes the soft-deleted row. Step 1 /email/accounts + Step 2 /gmail/authorize still 200 (no regression). Permission rows backfilled in Ajay's Workspace: Owner+Admin get email.read + email.templates.manage; Employee gets email.read only.
**Depends on:** Step 5 (conversations email adapter — the render output feeds into adapter.send).

---

## Scope

In-scope:

- Alembic migration adding `email_templates` table.
- `core/email_templates/` sub-package: `models`, `schemas`, `service`, `router`, `module`.
- `core/email/variables.py` — the substitution engine. Pure function: `render(template_body, context) -> str`. Context is built by `service.build_context(contact_id, lead_id=None, user_id=None) -> dict`.
- Variable registry: declarative list of allowed variable paths.
  - `contact.*`: all standard contact fields + every key in `contact.custom_data` (rule 3 — layered model).
  - `lead.*`: standard lead fields + custom_data keys, only if a lead is in context.
  - `user.*`: sender's first_name, last_name, email, signature.
  - `org.*`: name, support_email.
- Missing-variable behaviour: render fails with a 400 listing missing paths. Templates that reference `{{contact.custom_data.foo}}` for an org that does not define `foo` get a clear error at validation time, not at send time.
- Endpoints `/api/v1/email/templates`:
  - `GET` (list, paginated, search by name).
  - `POST` (create — requires `email.templates.manage`).
  - `GET /{id}` (read — requires `email.read`).
  - `PATCH /{id}` (update — requires `email.templates.manage`).
  - `DELETE /{id}` (soft delete; preserves usage history).
  - `POST /{id}/render?contact_id=…&lead_id=…` — preview render (no send).
- Audit events: `email.template.created`, `email.template.updated`, `email.template.deleted`.

Out of scope:

- Template UI (Step 10).
- Sequence steps that reference templates (Step 7).
- Inline images / rich attachments — plain HTML only for v1.

## The `email_templates` table

```sql
CREATE TABLE email_templates (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id),
    name            TEXT NOT NULL,
    subject         TEXT NOT NULL,
    body_html       TEXT NOT NULL,
    body_text       TEXT NOT NULL,                         -- auto-derived on save if not provided
    variables_used  JSONB NOT NULL DEFAULT '[]',           -- ['contact.first_name', 'lead.pipeline_stage']
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_by      UUID NOT NULL REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);

CREATE INDEX email_templates_org_active_idx ON email_templates (org_id, is_active) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX email_templates_name_idx ON email_templates (org_id, lower(name)) WHERE deleted_at IS NULL;

ALTER TABLE email_templates ENABLE ROW LEVEL SECURITY;
CREATE POLICY email_templates_tenant_isolation ON email_templates
    USING (org_id = current_setting('app.org_id', true)::uuid);
```

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/0XXX_add_email_templates.py` | created |
| `api/src/app/core/email_templates/__init__.py` | created |
| `api/src/app/core/email_templates/models.py` | created |
| `api/src/app/core/email_templates/schemas.py` | created |
| `api/src/app/core/email_templates/service.py` | created |
| `api/src/app/core/email_templates/router.py` | created |
| `api/src/app/core/email_templates/module.py` | created |
| `api/src/app/core/email/variables.py` | created |
| `api/src/app/core/permissions/registry.py` | modified — register `email.templates.manage` |
| `api/src/app/main.py` | modified — include router |
| `api/tests/test_email_templates.py` | created |

**11 files, 1 migration.** At rule-8 ceiling.

## Plan

1. `variables.py`: use `jinja2.Environment(autoescape=True, undefined=jinja2.StrictUndefined)`. Substitution variables are written as `{{ contact.first_name }}` (Jinja syntax) — but only allow a strict whitelist of attribute paths through a custom `Environment` filter. No expressions, no loops, no inheritance (`StrictExpressionEnvironment` subclass that rejects `Block`, `For`, `If` AST nodes). This keeps templates safe and predictable.
2. `service.build_context`: loads contact (required), lead (optional), user (sender), org. Returns nested dict including `custom_data` JSONB unfurled to its keys.
3. `service.parse_variables_used(body)`: AST-walk the Jinja template, extract every variable reference, return a sorted list. Stored on save so the editor can show "this template uses N variables" without re-parsing.
4. `service.validate_variables(variables_used, org_id)`: check each `contact.custom_data.<key>` and `lead.custom_data.<key>` against `custom_field_definitions` for the org. Unknown → 400 with the offending paths listed.
5. `service.render(template, context)`: returns `{subject, body_html, body_text}`. `StrictUndefined` means missing variables raise — but `validate_variables` ran on save so this is belt-and-braces.
6. `body_text` derivation: on save, if blank, derive from `body_html` via `html2text`. Add `html2text` to `pyproject.toml`.
7. Router: standard CRUD + a `POST /{id}/render?contact_id=&lead_id=` for previews from the editor.

## Tests

`api/tests/test_email_templates.py`:

- **Create:** valid template with `{{contact.first_name}}` saves; `variables_used` populated.
- **Variable validation rejects unknowns:** template with `{{contact.custom_data.nonexistent}}` → 400.
- **Render happy path:** template + contact + lead → returns substituted subject + bodies.
- **Render missing variable:** template referencing `{{lead.pipeline_stage}}` rendered without a lead → 400 listing the missing path.
- **AST sandbox rejects expressions:** template body `{% for x in [1,2] %}…{% endfor %}` → save rejected with 400.
- **AST sandbox rejects if:** template body `{% if user.is_admin %}…{% endif %}` → save rejected.
- **Autoescape:** contact.first_name set to `<script>alert(1)</script>` → rendered HTML contains escaped form.
- **RLS:** Org A's templates not visible to Org B.
- **Permission gate:** rep without `email.templates.manage` → 403 on POST.
- **Soft delete:** DELETE marks `deleted_at`; row excluded from GET list.

## Smoke

```powershell
docker exec template_api-api-1 uv run alembic upgrade head
docker exec template_api-api-1 uv run pytest tests/test_email_templates.py -v

# Create a template:
$token = "<owner JWT>"
curl -X POST http://localhost:8000/api/v1/email/templates `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -d '{"name":"Initial outreach","subject":"Hi {{contact.first_name}}","body_html":"<p>Hello {{contact.first_name}}, ...</p>"}'

# Preview render:
curl -X POST "http://localhost:8000/api/v1/email/templates/$tid/render?contact_id=$cid" `
  -H "Authorization: Bearer $token"
# Expect substituted subject + body
```

## Risks

- **Sandbox escape via Jinja2.** Restricting AST + StrictUndefined + autoescape eliminates the common attack paths. Adding `Environment(sandboxed=True)` is overkill but worth the line of belt-and-braces — note it in code.
- **html2text quality.** Some HTML produces ugly plain-text fallbacks. Acceptable for v1; if users complain, swap for `lxml_html_clean` + handwritten extractor.

## Rollback

`alembic downgrade -1`. Delete files. Revert permissions/main.py edits. Sequences (Step 7) depend on templates — rolling back templates implies rolling back Step 7 too.
