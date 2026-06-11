# Step 6 — Backend: `email_templates` table + variable substitution engine

**Goal:** Org-scoped library of reusable email templates with variable placeholders (`{{contact.first_name}}`, `{{lead.pipeline_stage}}`, `{{contact.custom_data.preferred_brand}}`). Templates store subject + body (HTML + plain) + variable schema discovered at render time. Render returns a fully-substituted MIME-ready payload.
**Track:** App Updates → Email
**Status:** Pending
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
