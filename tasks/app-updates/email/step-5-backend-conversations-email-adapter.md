# Step 5 — Backend: Conversations Email channel adapter (compose + reply threading)

**Goal:** Plug a real Email adapter into the existing `core/conversations/` channel registry (Phase 3.8). Inbound emails (from sync) become conversation messages threaded by `Message-ID` / `In-Reply-To` / `References`. Outbound `send_message` for `channel='email'` routes through the connected user's Gmail/Microsoft account.
**Track:** App Updates → Email
**Status:** Pending
**Depends on:** Steps 1–4. Phase 3.8 channel registry. Phase 3.10 conversations frontend (for compose surface).

---

## Scope

In-scope:

- `core/conversations/channels/email_adapter.py` — implements the `ChannelAdapter` protocol with `kind='email'`:
  - `send(conversation, body, attachments, from_user) -> Message` — composes a MIME message (subject inferred from conversation, threading headers set), delegates to `core.email.{gmail|microsoft}.send`. Persists outbound `Message` row with `delivery_state='sent'`.
  - `receive(raw_mime, account) -> Message` — parses the raw MIME, resolves the contact via `from` address, finds-or-creates a conversation (threading rules below), persists inbound `Message`, emits notification.
- Threading rules (in order):
  1. If `In-Reply-To` header matches an existing message's `Message-ID` → same conversation.
  2. Else if `References` chain contains a known `Message-ID` → same conversation.
  3. Else if subject (stripped of `Re:`/`Fwd:`/`Aw:`) matches an open conversation with the same contact in the last 30 days → same conversation.
  4. Else → new conversation.
- Per-account daily send cap: soft 200/day, hard 500/day. Configurable per-org via Settings later. Hard cap returns 429.
- Updates `email_accounts.daily_sent_count` atomically (Postgres `UPDATE … RETURNING`).
- Activity log: every send emits an `activities` row with `kind='email'`, `direction='outbound'`, `contact_id`, `user_id`, `metadata.message_id`.
- Adapter registers itself via `core/conversations/channels/__init__.py`.

Out of scope:

- Open/click tracking — Step 8.
- Template variable substitution — Step 6.
- Sequence enrollment — Step 7.
- Compose UI — Step 9.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/conversations/channels/email_adapter.py` | created |
| `api/src/app/core/conversations/channels/email_threading.py` | created — threading rules + Message-ID extraction |
| `api/src/app/core/conversations/channels/__init__.py` | modified — register the email adapter |
| `api/src/app/core/email/sync.py` (shared) | modified small — `receive_into_conversations` helper called by Gmail/Microsoft sync |
| `api/tests/test_conversations_email_adapter.py` | created |

**5 files.**

## Plan

1. `email_threading.py`: pure functions. `extract_message_id(headers) -> str`. `extract_thread_keys(headers) -> set[str]`. `normalize_subject(subj) -> str` (strip `Re:`, `Fwd:`, `Antw:`, `Re[2]:`, etc.).
2. `email_adapter.py`:
   - `send`: build a MIME message via `email.message.EmailMessage`. Set `Subject` (or `Re: …` if reply). Set `Message-ID` to `<{uuid}@furnicrm.app>`. If reply, set `In-Reply-To` + `References`. Render body as HTML + plain-text alternative. Call provider send. Persist `Message` row with `provider_message_id` (Gmail/Graph id).
   - `receive`: parse via `email.parser.BytesParser`. Resolve contact by `from` (lowercased, exact). If unmatched → drop (per the "personal inbox stays personal" invariant). Apply threading. Persist `Message` with `direction='inbound'`, `delivery_state='received'`, `body_html`, `body_text`. Emit in-app notification to the assigned rep.
3. Activity logging: same call as the existing WhatsApp adapter — `activities.log(...)`.
4. Daily-cap enforcement: in `send`, wrap the cap-check + increment in a single SQL statement using `WHERE daily_sent_count < hard_cap RETURNING …`. If no row updated, raise `HardCapExceeded` → router returns 429.
5. Register in `channels/__init__.py` so the existing conversations router (`POST /conversations/{id}/messages` with `channel='email'`) routes correctly.

## Tests

`api/tests/test_conversations_email_adapter.py`:

- **Send outbound:** mock provider send, call adapter, verify `Message` row + `activities` row, verify provider id captured.
- **Reply threading by In-Reply-To:** seed a conversation with outbound msg M1. Receive a raw MIME with `In-Reply-To: <M1's Message-ID>`. Verify same conversation.
- **Reply threading by References chain:** receive raw with `References: <unknown> <M1> <other>`. Verify same conversation.
- **Subject-based threading:** seed outbound subject "Quote for sofa". Receive a Re: with no In-Reply-To. Verify same conversation.
- **New conversation when no thread match:** unknown thread + unknown subject → new conversation.
- **Unmatched sender dropped:** raw from `random@person.com` (not in contacts) → adapter returns `None`, no rows created.
- **Daily soft cap warning logged but send succeeds:** at 200 sends, log warning, send completes.
- **Hard cap blocks:** at 500 sends, send raises `HardCapExceeded`.
- **Concurrent send increments counter atomically:** simulate two parallel sends; counter ends at 2.

## Smoke

```powershell
docker exec template_api-api-1 uv run pytest tests/test_conversations_email_adapter.py -v

# End-to-end (requires connected account from Step 2 + a contact whose email matches):
curl -X POST http://localhost:8000/api/v1/conversations/$cid/messages `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -d '{"channel":"email","body":"Hello from CRM","subject":"Test"}'
# Expect: 200, message row, real email arrives in customer's inbox
```

## Risks

- **MIME edge cases.** Apple Mail, Outlook, Gmail all emit slightly different `Message-ID` quoting and `References` whitespace. Use Python's `email` package strictly; never regex these headers.
- **Subject-threading false positives.** Two unrelated emails with the same subject within 30 days lump together. Acceptable for v1; can promote to a hashed subject + sender signature in v2 if needed.
- **Cross-account threading.** If two reps in the same org both email the same contact, threading should still treat replies as one conversation per contact-subject pair, not per-rep. The threading rules above already key off (org, contact) — verified by test.

## Rollback

Delete the new files. Revert channels/__init__.py registration. The conversations module returns 501 on `channel='email'` (same as before this track started).
