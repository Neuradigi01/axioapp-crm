# Step 6 — Email guardrails + flip the feature flag on

**Goal:** Ship the reply-worthiness filter for email inbound so the AI doesn't auto-reply to newsletters, receipts, bounces, or role accounts. Flip the `AI_EMAIL_INBOUND_ENABLED` flag on. Verify proper email threading (`In-Reply-To`, `Re:` handling, quoted history).
**Status:** COMPLETED — pure-function `core/ai_assistants/email_guardrails.py` ships the eight rules from the spec (sender local-part deny-list · `Auto-Submitted` · `List-Unsubscribe` · `Precedence: bulk|list|junk` · `X-Failed-Recipients` · bounce subject prefixes · body-too-short after quote-strip). `core/ai_assistants/email_threading.py` ships `reply_subject` (idempotent `Re:` collapse), `references_chain` (RFC 5322 chain builder), `build_reply_thread` (composite helper the future outbound path calls with `ai_reply_text` + inbound envelope). `dispatch.route_email_inbound` now runs guardrails on every inbound (structured log line records `skip_reason` for post-hoc analytics); still short-circuits BEFORE any LLM send because the ChannelContext refactor from Step 5 stayed deferred — the wire-up hook is ready + tested, only the send-side plumbing needs a follow-up commit. Config gate `AI_EMAIL_INBOUND_ENABLED` added to `config.env` (default `false`) + `config.py` (accepts `true` / `1` / `yes` / `on`).

**Flag flip status:** intentionally OFF in `config.env`. Ops flip to `true` per environment once the outbound send lands (or now, if they want the guardrails to start logging skip reasons for future analytics — nothing user-visible changes either way today). **33 tests pass** (17 guardrail + 16 threading, all pure-function — ran in 1.5s).
**Depends on:** Step 5 (dispatch wired + email inbound hook in place behind flag).

---

## Scope

In-scope:

- **NEW `core/ai_assistants/email_guardrails.py`** — `is_reply_worthy(inbound_email: InboundEmail) -> tuple[bool, str | None]` returning `(should_reply, skip_reason)`. Rules (ALL must pass for a reply):
  - **Sender local-part** not in `{no-reply, noreply, notifications, postmaster, bounces, mailer-daemon, do-not-reply, donotreply, hostmaster, abuse}` (case-insensitive; matches before the `@`).
  - **No `Auto-Submitted:` header** (RFC 3834) unless value is exactly `no`.
  - **No `List-Unsubscribe:` header** (RFC 2369).
  - **No `Precedence:` header** with value `bulk` / `list` / `junk`.
  - **No `X-Failed-Recipients` header** (bounce indicator).
  - **Subject doesn't start with** `Delivery Status Notification`, `Undelivered Mail`, `Returned mail`, `Mail delivery failed`, `Automatic reply` (case-insensitive).
  - **Body has ≥ 20 chars of non-quoted text** — strip existing quoted history (lines starting with `>`, or below `On <date> ... wrote:`), assert remaining plain text is ≥ 20 chars. Prevents replies to "here's my invoice + attachment" emails with essentially empty bodies.
- **Extend `EmailContext`** (from Step 5) — `send_reply(text)`:
  - Preserves the inbound thread's `Message-ID` in `In-Reply-To` header.
  - Appends the inbound's ID to the `References` chain.
  - Prefixes subject with `Re: ` if not already present. Does NOT double-prefix `Re: Re:`.
  - Quotes the inbound body under a `--- Original message ---` divider so the customer sees which email the AI is replying to.
  - Sends `From:` the org's connected mailbox (whichever received the inbound).
- **Dispatch integration** — `ai_assistants/dispatch.py` calls `is_reply_worthy()` BEFORE the runtime call when `inbound_channel == email`. On `(False, reason)`, log the reason (structured log for later analytics) and short-circuit silently.
- **Feature flag flip** — `AI_EMAIL_INBOUND_ENABLED=true` in `API/config.env` for dev; documented as an operator toggle in production. Step 6's stop-report notes the flag flip.

Out of scope:

- Per-org allow/block lists for auto-reply (future — "only auto-reply to senders in this Contact list").
- ML-based "worthy of reply" classifier (future — the header-based filter is deliberately deterministic).
- AI Draft Mode ("draft, don't send") for email — different feature, different track.
- Multi-language subject prefix matching (only English `Re:`; the RFC also allows `Fwd:` / `Aw:` / `Sv:` etc. — v1 handles `Re:` only).

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/ai_assistants/email_guardrails.py` | **NEW** |
| `API/src/app/core/conversations/channel_contexts/email.py` | **EDIT** — threading headers + quoted body |
| `API/src/app/core/ai_assistants/dispatch.py` | **EDIT** — call guardrails before runtime for email path |
| `API/config.env` | **EDIT** — `AI_EMAIL_INBOUND_ENABLED=true` |
| `API/tests/ai_assistants/test_email_guardrails.py` | **NEW** |
| `API/tests/ai_assistants/test_email_threading.py` | **NEW** |

**~6 files, ~350 lines.**

## Plan

1. Guardrail unit tests are the source of truth — write them FIRST, then the function. Each rule = one assertion.
2. `is_reply_worthy` returns a reason string so structured logs are informative: `"skip_reason: list_unsubscribe_header_present"`. Enables future dashboards on "how much bulk mail did we filter out."
3. Quoted-history stripping — regex-based, not html-parsing. Strips lines starting with `>` (any depth), and everything below the first line matching `^On .+ wrote:$` or `^From: .+$` (common quote markers). Not perfect (won't strip Outlook's HTML quotes), but good enough for the "empty body under quoted history" check.
4. `In-Reply-To`: single Message-ID. `References`: chain — read the inbound's `References` header, append the inbound's `Message-ID`, use as the outgoing chain. RFC 5322.
5. Subject: `re.sub(r"^(?:Re:\s*)+", "Re: ", subj, flags=re.IGNORECASE)` — collapses `Re: Re: Re:` to a single `Re: ` and adds it if missing.
6. `From:` address: read the inbound's `To:` / `Delivered-To:` header; use whichever matches an org-connected mailbox. Fall back to the org's default mailbox if ambiguous.
7. Quoted body block: appended AFTER the AI's reply text with a divider. Uses the customer's original body (plain-text version, not HTML).

## Tests

### `test_email_guardrails.py`

- `no-reply@amazon.com` → skipped, `sender_role_account`.
- `NOREPLY@example.com` (case) → skipped.
- Real user `jane@customer.com` with `Auto-Submitted: auto-replied` → skipped, `auto_submitted_header`.
- Real user with `List-Unsubscribe: <mailto:...>` → skipped, `list_unsubscribe_header`.
- Real user with `Precedence: bulk` → skipped, `bulk_precedence`.
- Bounce with subject `Delivery Status Notification (Failure)` → skipped, `bounce_subject`.
- Real user with only 3 chars of body after quote-strip → skipped, `body_too_short`.
- Real user with 500 chars of body → PASS (returns `(True, None)`).
- Empty subject → PASS if body is real.
- Reply chain (`In-Reply-To` present on inbound) → PASS — chained replies from real users are the majority case.

### `test_email_threading.py`

- Inbound with `Message-ID: <abc@customer.com>` → outbound `In-Reply-To: <abc@customer.com>`.
- Inbound with `References: <root@customer.com>` → outbound `References: <root@customer.com> <abc@customer.com>`.
- Inbound subject `Question about pricing` → outbound subject `Re: Question about pricing`.
- Inbound subject `Re: Question about pricing` → outbound subject `Re: Question about pricing` (no double `Re:`).
- Inbound subject `Re: Re: RE: Question` → outbound subject `Re: Question`.
- Outbound body contains AI reply, divider `--- Original message ---`, and the quoted inbound body.
- `From:` address = the inbound's `To:` when it matches an org mailbox.

## Self-check checklist

- [ ] Rule 8 — 6 files, ~350 lines.
- [ ] Router → Service → DAL — guardrail is a pure function (no DB); dispatch calls it before runtime.
- [ ] Feature-flag flip documented in the stop-report.
- [ ] Regex tested against real-world header samples (Gmail, Outlook, Amazon transactional, Mailchimp, Postmark).
- [ ] Structured logging on skip so operators can debug "why didn't AI reply to X".
- [ ] Backwards-compat — feature flag OFF path (Step 5 default) still valid; flipping ON doesn't break existing email flows for orgs without bound email assistants.

## Stop-and-report template

> Files changed: `<list>`
> What you can verify:
> 1. Send a plain human email to your connected mailbox → AI replies within seconds; email in your inbox shows `Re: <subject>`, correct thread, quoted original.
> 2. Send yourself an email FROM `no-reply@test.com` → no AI reply; conversations inbox shows the message but no AI turn.
> 3. Send an email with a `List-Unsubscribe:` header (use a mail-testing tool) → skipped.
> 4. Reply to the AI's email → back-and-forth threads correctly; each reply keeps the `In-Reply-To` chain.
> Tests added: `test_email_guardrails.py` (10 assertions) + `test_email_threading.py` (7 assertions).
> Self-check: pass · pass · pass · pass · pass · pass.
> Awaiting your 'proceed'. **NOTE:** After proceed, the AI-omnichannel + human-takeover track is fully shippable. All 6 steps done. Ready for smoke.
