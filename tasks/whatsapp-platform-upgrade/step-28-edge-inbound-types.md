# Step 28 — Edge inbound types (location, contact card, stickers)

**Goal:** Handle inbound message types not yet covered: location share, contact card (vCard), stickers. Reactions already covered in Step 7. Each renders distinctly in the thread.
**Status:** COMPLETED
**Depends on:** Phase 2 closed (media + interactive infrastructure).

---

## Scope

In-scope:
- Webhook handler extension for:
  - `location` — capture lat / lng / name / address; render with map thumbnail + "Open in Maps" link.
  - `contacts` (vCard) — capture name + phone(s) + email(s); render with contact card + "Add to contacts" CTA.
  - `sticker` — capture sticker URL + animated/static; render as image bubble with sticker styling.
- Optional outbound location share (rare; included as small extension):
  - Composer "+" menu → "Location" → map picker or paste coords → send.
- Frontend renderers in `message-bubble.component.ts`:
  - Location bubble (map thumb via static-map service or placeholder)
  - vCard bubble (name + phone + Add CTA)
  - Sticker bubble (image with no caption + sticker frame)
- "Add to contacts" → opens existing contacts/create-from-vcard flow.

Out of scope:
- Outbound stickers — not typical CRM use; defer.
- Inbound video calls / voice notes deep-handling — voice already covered by Step 5 audio.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/conversations/adapters/whatsapp.py` | Parse new types in webhook |
| `API/src/app/core/conversations/models.py` | Add `payload_type` enum value if needed |
| `API/alembic/versions/<ts>_edge_payload_types.py` | **NEW** (conditional) |
| `APP/.../conversations/thread/message-bubble.component.ts` | Render new types |
| `APP/.../conversations/thread/location-bubble.component.ts` | **NEW** |
| `APP/.../conversations/thread/vcard-bubble.component.ts` | **NEW** |
| `APP/.../conversations/thread/sticker-bubble.component.ts` | **NEW** |
| `APP/.../conversations/composer/composer.component.ts` | Add "Location" entry (optional outbound) |
| `API/tests/conversations/test_edge_inbound.py` | **NEW** |

**~9 files. ~400 lines.**

## Plan

1. Webhook parsing: add three branches per Meta spec; persist into existing JSON payload.
2. Static map: use OpenStreetMap tile or a placeholder thumbnail with coords text fallback.
3. vCard parse: keep raw vCard + extracted fields (name + primary phone).
4. Sticker render: standard image bubble with a small "Sticker" pill label.
5. "Add to contacts" wires existing contacts/create endpoint with vCard fields pre-filled.
6. Tests cover parse + render contract.

## DB changes / migrations

Probably none if payload JSONB already accepts any shape. Otherwise tiny enum extension.

## Tests

5 pytest + 3 Jest.

## Smoke

```
1. Customer shares location → conversation shows map thumbnail + "Open in Maps".
2. Customer shares contact card → vCard bubble shows name + phone + Add CTA.
3. Click Add → contact prefilled, save.
4. Customer sends sticker → renders as image with sticker label.
5. Owner sends outbound location via composer → recipient receives map.
```

## Risks

- Static map provider rate limits — fall back to coords text.
- vCard format variations — robust parser; raw saved for diagnostics.

## Self-check (10 rules)

All `core/conversations/`. ✓. org_id + RLS preserved. ✓. No custom-field changes. ✓. Static UI. ✓ N/A. No registry change. ✓. Existing perms. ✓. pack.yaml untouched. ✓. 9 files / ~400 lines. ✓. Stop-report. ✓. No TODOs. ✓.

## Stop & report

```
Step 28 — Edge inbound types
Files: 9
Verify: location / vCard / sticker inbound render; optional outbound location.
Tests: 5 pytest + 3 Jest.
Next: Step 29 — campaign A/B testing.
Awaiting "proceed".
```
