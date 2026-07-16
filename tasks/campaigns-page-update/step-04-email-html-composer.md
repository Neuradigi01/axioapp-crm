# Step 04 — Email HTML composer + `body_html` on MessageTemplate

**Goal:** Email templates carry a real HTML body (not just plain text), authored via a rich composer with a merge-tag inserter and a live inbox-style preview. The campaign create modal can either pick a template (which supplies the HTML) or author a one-off HTML body inline.
**Track:** Campaigns page update — Email
**Status:** Pending
**Depends on:** Step 03 (Campaign has `subject`, `preheader`, `sender_name` fields)

Screen references in [`preview.html`](preview.html):

- **Screen 4 · Create Campaign — Email** — the `Body — HTML composer` block: toolbar with B/I/U · Link · Image · List · Button · **Insert @variable ▾**, textarea, right-side inbox preview panel.
- Also the same composer is used on **Create Email Template** (sidebar view).

---

## Scope

Backend adds one column (`MessageTemplate.body_html`) + one validator + a lightweight HTML sanitizer. Frontend swaps the plain textarea for a rich editor + inserts the "Insert variable" dropdown + adds a right-side inbox preview panel.

**Explicitly NOT in this step:**

- Dispatch (Step 05).
- Unsubscribe-footer auto-append (Step 06 — the footer is injected at dispatch, not stored on the template).
- Domain verification (Step 07).

## Schema

Migration `00XX_message_template_body_html.py`:

| Column on `tbl_message_templates` | Type | Constraint | Why |
|---|---|---|---|
| `body_html` | TEXT | nullable | HTML body for Email templates. WhatsApp templates keep `body_text` only. |
| `body_text_fallback_auto` | BOOLEAN | NOT NULL DEFAULT `true` | If `true`, dispatch auto-derives plain-text from HTML when `body_text` is empty (Gmail's multipart fallback). If `false`, both must be provided by the user. |

No new tables. No index — existing lookups are by id / channel / org.

Alembic up + down verified inside `API/docker-helper.cmd`.

## Backend

### Sanitizer

New module `api/src/app/core/templates/sanitizer.py`:

- Wraps `bleach` (already a dep — check `pyproject.toml`; if missing, add it).
- Allowed tags: `p`, `br`, `strong`, `em`, `u`, `s`, `a`, `ul`, `ol`, `li`, `blockquote`, `h1`–`h4`, `img`, `hr`, `span`, `div`, `table`, `thead`, `tbody`, `tr`, `td`, `th`.
- Allowed attributes: `href` (on `a`, must start `http://` or `https://` or `mailto:`), `src` + `alt` + `width` + `height` (on `img`), `style` (on all — CSS allowlist: `color`, `background-color`, `font-weight`, `font-style`, `text-decoration`, `text-align`, `padding`, `margin`, `border`, `border-radius`).
- Strip `<script>`, `<iframe>`, `<object>`, event handlers (`on*`), `javascript:` URLs.
- Function `sanitize_email_html(html: str) -> str`.
- Function `derive_plain_text(html: str) -> str` — uses `html2text` or a simple BeautifulSoup traversal to produce a text fallback.

### `templates/schemas.py`

Extend `TemplateCreate` / `TemplateUpdate` / `TemplateRead`:

```python
body_html: str | None = Field(None, max_length=200_000)
body_text_fallback_auto: bool = True
```

Model-level validator on create + update:

- When `channel == email`:
  - At least one of `body_text` or `body_html` must be provided.
  - If both are empty → 422 "Email templates require body_text or body_html".
- When `channel == whatsapp`: `body_html` must be null (WA templates are plain text with placeholders).

### `templates/service.py`

- On create/update, if `body_html` is present, run `sanitize_email_html()` before persisting. Store the sanitized version.
- If `body_text_fallback_auto=true` and `body_text` is empty, derive it via `derive_plain_text(body_html)` and store both.
- Existing merge-tag placeholders (`{{first_name}}`, `{{email}}`, `{{custom_data.*}}`) are preserved verbatim by the sanitizer (they look like normal text to bleach).

### Endpoints

No new endpoints. Existing `POST /templates` + `PATCH /templates/{id}` accept the new fields.

## Frontend

### Create / Edit Email template page

Path: `app/src/app/features/user/core/templates/email/` (create if the folder doesn't exist for the Email-specific create page).

- Replace the plain textarea with a rich editor. Use **TipTap** (already the ecosystem-standard for Angular) if the repo has it — otherwise fall back to a `[contenteditable]` div with a light toolbar. Do not add Quill; check `package.json` first and reuse whichever rich-text lib is already present.
- Toolbar (matches the mockup): **B**, *I*, U, · Link, Image (URL-only in this step — file upload can come later), Bulleted list, Numbered list, Button (inserts a styled `<a>` with the zinc-900 CTA style), · **Insert @variable ▾** dropdown.
- Merge-tag dropdown: options come from a small utility `mergeTagsFor('contact')` — returns `first_name`, `last_name`, `full_name`, `email`, `phone`, `company`, plus any `custom_data.*` keys from the org's custom-field definitions. Selecting an option inserts the placeholder at the caret.
- Preview panel on the right (sticky): renders the sanitized HTML inside the inbox-style card from the mockup (Gmail-style From / To / Date header + subject + body + footer stub). Preview updates on editor blur.
- On save, the HTML is sent to the server, which re-sanitizes and stores. Never trust the frontend sanitizer for security.

### Campaign create modal — Email branch

- When "Use template" is selected, the picker (list Email templates) shows name + subject preview + last-edited date. On select, the modal locks the subject / body preview to the template.
- When "Compose inline" is selected, the modal renders the same rich editor + preview + merge-tag inserter as the template page. The result is stored on the campaign row (already-existing `template` column takes text — keep that for backwards compat with WA free-text, but for Email store the HTML in a new column below).

Add one column here:

| Column on `tbl_campaigns` | Type | Constraint | Why |
|---|---|---|---|
| `body_html` | TEXT | nullable | Ad-hoc HTML body when no template is picked. Mutually exclusive with `template_id` — existing `_exactly_one_template_source` validator extended to accept `body_html` OR `template_id`. |

Small extension of Step 03's schema-check validator to include `body_html` as a valid "template source" for Email.

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/00XX_message_template_body_html.py` | created |
| `api/alembic/versions/00XX_campaign_body_html.py` | created (separate migration, or combined — one or two migrations, up to implementer) |
| `api/src/app/core/templates/sanitizer.py` | created |
| `api/src/app/core/templates/models.py` | modified — two new columns |
| `api/src/app/core/templates/schemas.py` | modified — extended schemas + channel-branched body validator |
| `api/src/app/core/templates/service.py` | modified — sanitize on create/update |
| `api/src/app/core/campaigns/models.py` | modified — `body_html` column |
| `api/src/app/core/campaigns/schemas.py` | modified — extend the "exactly one template source" validator |
| `api/tests/test_email_html_sanitizer.py` | created — sanitizer unit tests |
| `api/tests/test_email_template_body_html.py` | created — API tests for template create/update with HTML |
| `app/src/app/features/user/core/templates/email/email-template-editor.component.{ts,html,scss}` | created or modified — rich editor + merge-tag dropdown + preview panel |
| `app/src/app/features/user/core/templates/email/email-template-editor.spec.ts` | created |
| `app/src/app/features/user/core/campaigns/create-campaign-modal.component.{ts,html}` | modified — inline compose branch when no template picked |

**~10 files + 2 migrations.** At the edge of the per-step rule. If this feels heavy at implementation time, split: **04a** = template `body_html` + sanitizer + template UI; **04b** = campaign inline compose + campaign `body_html`. Preferred: keep as one, split only if line count exceeds ~400.

## Tests

`test_email_html_sanitizer.py`:

- Strips `<script>`, `<iframe>`, event handlers, `javascript:` URLs.
- Preserves allowed tags + attributes.
- Merge-tag placeholders (`{{first_name}}`) pass through unmodified.
- `derive_plain_text()` produces reasonable text (no HTML tags, whitespace normalised).

`test_email_template_body_html.py`:

- **Happy path:** create Email template with `body_html` + `body_text=null` + `body_text_fallback_auto=true` → 201, DB row has sanitized HTML + auto-derived text.
- **Both provided:** `body_html` + `body_text` explicit → both stored verbatim (sanitizer applied to HTML).
- **Neither provided:** empty both → 422.
- **WhatsApp rejected:** create WA template with `body_html` set → 422.
- **XSS attempt:** submit `<script>alert(1)</script><p>hi</p>` → stored HTML has only `<p>hi</p>`.

`email-template-editor.spec.ts`:

- Merge-tag dropdown inserts placeholder at caret.
- Toolbar bold/italic/underline apply correctly.
- Preview panel updates on blur.

## Verification

Ajay's Workspace:

1. **Templates → + Create Template**. Channel = Email.
2. Toolbar renders. Type body text, format with bold + italic. Insert a `{{first_name}}` merge tag from the dropdown.
3. Add a link + a Button (CTA). Save.
4. Reload the template — HTML persisted with formatting intact. Merge tag still `{{first_name}}` (not resolved yet — that happens at dispatch).
5. Try to save a template body containing `<script>alert('xss')</script>` — save succeeds but the stored HTML has no `<script>` tag.
6. **Campaigns → + New Campaign → Email → Use template** → the new Email template appears in the picker with subject preview.
7. Alternatively **Compose inline** → same editor, save the campaign as Draft, verify the `campaigns.body_html` column is populated (via psql).

## Self-check (fill in before the stop-and-report)

- 10 rules: line-by-line
- Layered architecture: `service.py` calls sanitizer helper (`utils`-style, no DB); DAL only touches columns
- Sanitizer coverage: rerun XSS test cases before shipping
- Reuse: existing merge-tag placeholder syntax; existing template model/schema — extended, not forked
- Query efficiency: no changes to fetch patterns
- Tooling: prettier + eslint + ruff on all touched files; migrations verified up + down

## Awaiting your `proceed`

Done means: Email templates + inline campaign bodies carry sanitized HTML, merge-tag inserter works, preview panel renders, XSS blocked server-side, spec + pytest suites green, browser smoke green. Emails still don't send — Step 05 wires the dispatch.
