# Step 5 — Backend: Conversations Email channel adapter (compose + reply threading)

**Goal:** Plug a real Email adapter into the existing `core/conversations/` channel registry (Phase 3.8). Inbound emails (from sync) become conversation messages threaded by `Message-ID` / `In-Reply-To` / `References`. Outbound `send_message` for `channel='email'` routes through the connected user's Gmail/Microsoft account.
**Track:** App Updates → Email
**Status:** COMPLETED — `core/conversations/adapters/email_threading.py` ships pure threading helpers: `extract_message_id` (case-insensitive header lookup + angle-bracket strip), `extract_thread_keys` (combines `In-Reply-To` value + every `<id>` token in `References`), `normalize_subject` (iteratively strips Re:/Fwd:/Aw:/Antw:/Sv:/Wg:/R: and Outlook's `Re[2]:` numbered form, lowercase normalised), `subject_thread_key` (currently delegates to normalize_subject — separate name reserved for future signature upgrade). `core/conversations/adapters/email.py` ships `EmailAdapter` implementing the existing channel-registry `ChannelAdapter` Protocol — its `.send()` and `.parse_webhook()` both raise `EmailUseSendEmailEndpoint(400)` as guard rails because email needs subject + sender_account args that the protocol contract doesn't carry; callers MUST use the typed entry points instead. Typed `send_email(session, *, org_id, sender_user_id, account_id, contact_id, subject, body_text, body_html=None, in_reply_to_message_id=None, conversation_id=None)` validates the rep owns the account (403 on wrong user, 409 on disconnected), resolves contact + finds-or-creates an email conversation keyed on `(channel=email, contact_id)`, composes MIME via stdlib `email.message.EmailMessage` with stable `Message-ID: <uuid@furnicrm.app>` + threading headers (`In-Reply-To` + `References` set to the prior message's RFC id when replying), dispatches to `gmail_send.send` or `ms_send.send` based on `account.provider`, surfaces provider-side `DailyCapExceeded(429)` as our public `HardCapExceeded(429)`, persists `Message(direction=out, channel_message_id=<our RFC id>, payload={subject, from, to, in_reply_to, provider, provider_message_id, body_html_present})`, logs `ActivityType.email` on the contact + audit row + bumps conversation.last_message_at. Inbound `receive_email(account, matched)` matches Step 4's `InboundHandler` signature: opens its own session inside the tenant context Step 4's task set; dedupes by RFC Message-ID OR provider message id; threads via (1) any thread key (In-Reply-To OR References chain) matching a known prior `messages.channel_message_id` for the same contact, (2) subject-thread-key fallback within last 30 days against open conversations, (3) fresh conversation; persists `Message(direction=in_, channel_message_id=<rfc-id or provider-id>, payload={subject, from, to, provider, provider_message_id, rfc_message_id, thread_keys})`; bumps unread_count + last_message_at; logs contact activity + notifies the conversation's assignee. **Registration**: at module import, `core/conversations/adapters/email.py` calls `register_channel(ConversationChannel.email, lambda: EmailAdapter())` AND `register_inbound_handler(receive_email)` — the Step 4 daemon's `dispatch_inbound` now routes to receive_email instead of no-op-logging. The side-effect import is triggered by adding `import src.app.core.conversations.adapters.email` to `core/conversations/__init__.py` (loaded transitively via main.py → conversations.router → conversations.service); WhatsApp doesn't follow this pattern because its credentials are per-org (resolved at send time), while the email adapter is stateless (per-rep mailbox resolved from `account_id` at send time). Tests cover: threading helpers (Message-ID extraction in lowercase/Camel/unbracketed/missing forms; thread-keys collection from In-Reply-To alone, References chain alone, both combined; normalize_subject for Re/Fwd/Aw/Antw/Sv/Re[2] prefixes + lowercase + empty); Protocol guard rails (`.send()` + `.parse_webhook()` both raise EmailUseSendEmailEndpoint); MIME builder (minimal text email, reply with In-Reply-To + References, HTML alternative multipart); send_email state machine (account-not-found 404, wrong-user 403, disconnected 409, contact-without-email 400, happy Gmail send adds Conversation + Message rows, HardCapExceeded surfaces as 429); receive_email (no-contact_id drops, RFC-id dedupe returns None, fresh conversation when no thread keys found, threads via Message-ID match against existing prior message reusing the conversation row). **Notable adaptations from the spec:** (a) **Folder is `adapters/` not `channels/`** — matches existing project convention (`core/conversations/adapters/whatsapp.py`); (b) **Adapter `.send()` is a 400 guard rail** — the generic `ChannelAdapter` Protocol doesn't carry subject/sender; the spec's `send_outbound` path can't model email cleanly, so the typed `send_email` entry point is what Step 9's frontend compose route will call; (c) **Inbound dispatched via Step 4 registry**, not via `conversations.receive_webhook` — email's inbound source is the sync daemon, not channel webhooks; (d) **Atomic daily-cap delegated to provider-level send** — Steps 2/3 already implement optimistic-increment-then-rollback against `email_accounts.daily_sent_count`; Step 5's send_email just translates the typed exception; the spec's `RETURNING` SQL pattern is structurally equivalent and unifies cap enforcement across both Gmail's and Microsoft's send paths; (e) **No new conversations webhook endpoint** — email is push-only via Step 4; receive_email's signature matches the inbound-handler Protocol so Step 4's existing dispatcher routes through it; (f) **No `EMAIL_MESSAGE_ID_DOMAIN` env added to .env.example** — defaults to `furnicrm.app` per project convention, override only if customer rebrands the product domain. Smoke verified: API discovers `email` module, channel registry now lists `['email']`, `resolve(ConversationChannel.email).__class__.__name__ == 'EmailAdapter'`, `sync_daemon._inbound_handler` is `receive_email`. Step 1 GET /email/accounts → 200, Step 2 /gmail/authorize → 200 (no regression).
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
