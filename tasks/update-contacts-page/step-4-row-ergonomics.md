# Step 4 — Row ergonomics: click-to-call / mailto / WhatsApp + URL-sync + duplicate warning + CSV export + page-size

**Goal:** turn the contacts list into a working sales tool. Phone & email cells become actionable links. Filter state survives refresh / share. Create modal flags duplicates before save. Admins can export the current filter as CSV. Page size is selectable.

**Depends on:** Step 3 frontend.

## Files changed

### New shared (re-used by every other update-* track)
- `APP/src/app/features/user/core/shared/phone-link.directive.ts` — wraps a phone string in a `<a href="tel:...">` with normalised dialable digits.
- `APP/src/app/features/user/core/shared/whatsapp-link.directive.ts` — wraps a phone string in `<a href="https://wa.me/...">` with E.164 digits.
- `APP/src/app/features/user/core/shared/mail-link.directive.ts` — wraps an email in `<a href="mailto:...">`.
- `APP/src/app/features/user/core/shared/url-filter-state.directive.ts` — round-trips a `Record<string, signal>` ↔ query params.

### Modified backend
- `API/src/app/core/contacts/router.py` — `GET /contacts/export.csv`, `GET /contacts/check-duplicate`.
- `API/src/app/core/contacts/service.py` — `export_contacts_csv(...)`, `check_duplicate(...)`.

### Modified frontend
- `APP/src/app/features/user/core/contacts/contacts-api.service.ts` — `exportCsv(query)`, `checkDuplicate({ phone?, email? })`.
- `APP/src/app/features/user/core/contacts/contacts-list.page.ts` — page-size signal, URL state wiring, CSV download handler.
- `APP/src/app/features/user/core/contacts/contacts-list.page.html` — Export CSV button, page-size dropdown, phone/email link directives applied to cells.
- `APP/src/app/features/user/core/contacts/contact-form-modal.component.ts` — duplicate-check debounced on phone/email blur.
- `APP/src/app/features/user/core/contacts/contact-form-modal.component.html` — duplicate-warning banner.
- `APP/src/app/features/user/core/contacts/contact-detail.page.html` — phone/email/WhatsApp icons in header dl.

### Tests
- `API/tests/core/contacts/test_export_and_duplicate.py` (new).

## Backend endpoints

### `GET /contacts/export.csv`
Same query params as `GET /contacts` (q, source, tag, assigned_to_id, custom.*). **No pagination** — streams the whole filter as CSV. Hard cap at 50k rows (return 422 with "filter too broad, narrow it down" beyond that). Requires `contacts.read`.

Columns: `id, full_name, phone, email, source, tags, assigned_to_name, last_activity_at, created_at, updated_at`. Custom fields **not** included in v1 (would require resolving the org's custom field schema; punt to a v2 step).

Stream with `StreamingResponse` + `csv.writer` writing to a `StringIO` buffer flushed per chunk. Content-Disposition `attachment; filename="contacts-{org_slug}-{YYYY-MM-DD}.csv"`.

### `GET /contacts/check-duplicate?phone=...&email=...`
Returns `{ "matches": [{ "id", "full_name", "phone", "email" }] }`. Empty matches = clean. Requires `contacts.read`. Hits the existing GIN trigram / phone / email indexes.

Phone match is normalised: strip non-digit, suffix-match last 10 digits (handles +91 vs no-prefix). Email match is case-insensitive exact.

## Frontend — link directives

```typescript
@Directive({ standalone: true, selector: '[appPhoneLink]' })
export class PhoneLinkDirective {
  appPhoneLink = input.required<string | null>();
  // sets host href = `tel:${normalised}`, role=link, aria-label, etc.
}
```

Each directive accepts the raw string and:
- Returns nothing if input is null/empty → host element renders inert.
- Otherwise wraps in an `<a>` (or applies link attrs to the host).

Used like:
```html
<a [appPhoneLink]="item.phone">{{ item.phone ?? '—' }}</a>
<a [appWhatsappLink]="item.phone"><lucide-icon name="message-circle" /></a>
<a [appMailLink]="item.email">{{ item.email ?? '—' }}</a>
```

## Frontend — `UrlFilterStateDirective`

Generic, no contacts-specific logic. Takes a record of signal getter/setter pairs and a query-key map:

```typescript
@Directive({ selector: '[appUrlFilterState]', standalone: true })
export class UrlFilterStateDirective {
  appUrlFilterState = input.required<UrlFilterStateConfig>();
  // ngOnInit: read query params → set signals
  // effect: signals change → router.navigate with merged queryParams
}
```

Wire to `contacts-list.page.ts` via:
```typescript
readonly urlState: UrlFilterStateConfig = {
  q: { signal: this.q, queryKey: 'q' },
  source: { signal: this.sourceFilter, queryKey: 'source' },
  tag: { signal: this.tagFilter, queryKey: 'tag' },
  assigned_to_id: { signal: this.assigneeSignal, queryKey: 'assignee' },
  sort: { signal: this.sortKey, queryKey: 'sort' },
  order: { signal: this.sortOrder, queryKey: 'order' },
  page: { signal: this.page, queryKey: 'page' },
};
```

Refresh / share / browser-back all preserve state.

## Frontend — duplicate warning

In `contact-form-modal.component.ts`, watch the `phone` and `email` controls. On `valueChange` debounced 400ms (and on blur), call `api.checkDuplicate({ phone, email })`. Render a small yellow banner in the modal:

> ⚠️ A contact with this phone exists: **Ramesh Verma** [view]

Save is **not** blocked — the user can still create (legitimate cases: two family members share a phone). The link opens the existing contact in a new tab.

## Frontend — CSV export button

Header gets a third action between Import and New: **Export CSV**. Click triggers `api.exportCsv(currentQuery())` which builds a `Blob` from the streamed body and triggers a download. Permission-gated on `contacts.read` (everyone who can see the list can export).

Show a loading spinner inline while the stream is in-flight. Cancel button if the user navigates away mid-stream.

## Frontend — page-size dropdown

In the pagination row, add `<select>` with options `25 / 50 / 100`. Wire to a `pageSize` signal (default `25`); reload when it changes. URL-sync via the same `UrlFilterStateDirective` (`queryKey: 'size'`).

## Lucide icons used

`download`, `message-circle` (WhatsApp), `mail`, `phone`, `alert-triangle` (duplicate warning). Register all in `app.config.ts`.

## Acceptance

1. Phone cell in list → click → phone dialer opens / softphone receives the number.
2. Mail icon → opens default mail app to a draft.
3. WhatsApp icon → opens `wa.me/<digits>` in a new tab.
4. Refresh `/user/contacts?q=ramesh&assignee=me&sort=last_activity_at&order=desc&page=2` → list loads with all filters restored.
5. Create modal: typing an existing phone shows the yellow banner with the existing contact's name + link.
6. Export CSV button → downloads `contacts-ajays-workspace-2026-05-27.csv` with the current filter applied.
7. Page-size dropdown → switching to 100 reloads with 100 rows; URL reflects `&size=100`.
8. Detail page header phone → click-to-call works; WhatsApp icon next to it works.

## Self-check vs the 10 rules

- ✅ Rule 1 — shared directives in `core/shared/`, no pack code.
- ✅ Rule 5 — sidebar / module registry untouched.
- ✅ Rule 8 — 13 files (4 new shared, 2 modified backend, 6 modified contacts FE, 1 test). Right at the limit.
- ✅ Rule 10 — no TODOs; CSV streams server-side properly, dup check is real not a stub.

## Stop-and-report template

> ✅ Step 4 complete.
> **Files changed:** 13 (4 new shared FE directives, 2 modified backend, 6 modified contacts FE, 1 new test).
> **What you can verify:**
> 1. tel / mailto / WhatsApp links work on list + detail.
> 2. URL state round-trips (refresh, share link, browser-back).
> 3. Duplicate warning fires on existing phone/email in create modal.
> 4. CSV export downloads with the current filter applied.
> 5. Page-size dropdown switches between 25/50/100.
> **Tests added:** `tests/core/contacts/test_export_and_duplicate.py` (4 cases: csv shape, csv cap, dup match by phone suffix, dup match by email case-insensitive).
> **Self-check:** all 10 rules ✅.
> **Track complete.** The shared primitives (`PhoneLink`, `WhatsappLink`, `MailLink`, `UrlFilterStateDirective`, `ReassignModal`, `BulkActionBar`, `ConfirmDialog`, `RelativeTimePipe`, `UsersDirectoryService`) are now ready for `update-leads-page/`, `update-walkins-page/`, `update-appointments-page/`, `update-tasks-page/`, `update-staff-offboarding/`.
> Awaiting your **"proceed"** before moving to the next folder (recommend `update-leads-page/`).
