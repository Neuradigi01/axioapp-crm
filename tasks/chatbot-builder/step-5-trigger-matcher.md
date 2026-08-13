# Step 5 — Trigger matcher (google-re2, priority, idempotency, opt-out, precedence)

**Goal:** Subscribe to the Step 4 events, match them against bot trigger configs using `google-re2`, apply priority + idempotency + opt-out gates, and start bot runs — with explicit precedence over the existing inline auto-reply path.
**Depends on:** Steps 3, 4
**Status:** Pending

## Scope

**In-scope**
- Add `google-re2` (or `re2`) dependency.
- `core/chatbots/trigger_matcher.py` — matcher with LRU-cached compiled regex.
- Subscribe the matcher to `whatsapp.message_received` + `email.message_received` in `core/chatbots/module.py`.
- Precedence rule (Decision §12): if any active bot matches, skip the inline auto-reply / keyword-rules for that message. Signal via a new `chatbot_matched` flag on the inbound-message processing context OR by making the matcher run BEFORE the inline path and setting a per-message skip flag.
- Idempotency check: `has_active_run_for(bot_id, conversation_id)` — parked runs consume the inbound message instead of spawning new runs.
- Opt-out gate: reuse `core/workflows/compliance.py` to check marketing consent + block-contact before matching.
- Priority resolution: first-match-wins by `priority DESC, created_at ASC`.
- Length cap: match on first 4 KB of inbound text (Case #19).

**Out of scope**
- Actually starting the run (calls into Step 6 engine which lands next; for this step the matcher just picks the winning bot and calls a stub `engine.start_run()`).

## Files to touch

- `API/src/app/core/chatbots/trigger_matcher.py` (created)
- `API/src/app/core/chatbots/module.py` (modified — event subscriptions)
- `API/src/app/core/chatbots/data_access.py` (modified — add `list_active_bots_by_channel(org_id, channel)`, `has_active_run_for_bot_conversation(bot_id, conversation_id)`, `insert_skip_diagnostic()`)
- `API/src/app/core/conversations/service.py` (modified — invoke matcher AT THE RIGHT POINT for the precedence rule; likely before the inline auto-reply path)
- `API/pyproject.toml` (modified — add `google-re2` dep)

## Plan

1. Add `google-re2` — verify install works on the container's Linux base; document Windows dev workaround if necessary.
2. `trigger_matcher.py`:
   - `match_inbound(event)` → returns winning `Chatbot` or `None`.
   - Enumerates active bots in the org via `list_active_bots_by_channel(org_id, event.channel)` (channel filter honored per bot).
   - For each bot, evaluates trigger config: keyword (word-boundary case-insensitive by default), regex via `re2.compile(pattern)` (LRU cache keyed on `(pattern, case_sensitive)` — invalidate on bot save), `first_message_only` toggle checked against payload flag.
   - Sorts matches by `priority DESC, created_at ASC`; returns first.
   - For losers, insert `chatbot.trigger.skipped_by_priority` diagnostic rows so operators see "why didn't my bot fire" (fed into a diagnostics UI in a follow-up track).
3. Wire subscribers in `module.py`:
   - `bus.subscribe("whatsapp.message_received", on_inbound)`
   - `bus.subscribe("email.message_received", on_inbound)`
   - `on_inbound(event)` runs opt-out gate → matcher → `engine.start_run(bot, event)` OR resume via idempotency check.
4. Precedence integration in `conversations/service.py`:
   - After persisting the inbound message but BEFORE the existing inline auto-reply, run a synchronous "any-bot-matches?" pre-check. If yes AND `org.chatbot_disable_inline_when_active_bot=true`, skip inline auto-reply + inline keyword rules for this message.
   - The async `bus.publish` still fires — it drives the actual bot run.
   - This dual path (sync precedence check + async bot run) avoids a race where the inline auto-reply sends first and the bot sends second.
5. Regex compile cache — `functools.lru_cache(maxsize=256)`; invalidated by bumping a version counter when a bot with regex trigger is saved (cheap: check `bot.updated_at` in the cache key).

## DB changes / migrations

Add `org.chatbot_disable_inline_when_active_bot BOOLEAN DEFAULT TRUE` on `tbl_organizations` — one small migration. Revision `0188_chatbot_inline_precedence`.

Optional: `tbl_chatbot_trigger_diagnostics (id, org_id, bot_id, conversation_id, reason, created_at)` for the skip-diagnostics — small table, TTL-swept 90 days.

## Tests to add

Location: `API/tests/core/chatbots/test_trigger_matcher.py`

- `test_keyword_case_insensitive` (T6)
- `test_regex_case_sensitive` (T7)
- `test_channel_filter_whatsapp_only` (T8)
- `test_regex_over_500_chars_rejected_at_save` (T9)
- `test_redos_regex_safe_under_re2` (T10) — pattern `(a+)+$` against 5 KB of `a`s completes in <100 ms.
- `test_priority_higher_wins` (T11)
- `test_priority_tie_created_at_wins` (T11)
- `test_opted_out_contact_no_match` (T13)
- `test_active_run_prevents_duplicate` (T12) — second matching inbound feeds the parked run instead of spawning a new one.
- `test_inline_auto_reply_skipped_when_bot_matches` — precedence rule.
- `test_inline_auto_reply_fires_when_no_bot_matches` — regression.

## Verification checklist

**Backend**
- [ ] `pytest tests/core/chatbots/test_trigger_matcher.py` green.
- [ ] Manual test: create a bot with keyword `test`, send inbound "test hello" → bot run visible in DB; inline auto-reply did NOT fire.
- [ ] Manual test: `test_redos_regex_safe_under_re2` completes in <100ms.

**Frontend** — N/A.

**Code review**
- [ ] Matcher runs against the 4 KB text cap.
- [ ] Cross-org isolation asserted in matcher (redundant with Step 4's assertion but defense in depth).
- [ ] LRU cache is bounded and invalidates on bot save.

## Self-check (10 rules)

- [ ] `core` didn't import `packs`
- [ ] `org_id` filters every bot enumeration query
- [ ] Sidebar/permissions N/A
- [ ] Reuse — reused compliance.py, event bus
- [ ] Query efficiency — enumerate matches with one query (`WHERE org_id = X AND status = 'live' AND (channel = 'any' OR channel = ?)`), no per-bot query
- [ ] Zero TODOs

## Stop & report

Report the matcher's decision flow with a real example log (input → shortlist → winner → skip diagnostics). Await "proceed".
