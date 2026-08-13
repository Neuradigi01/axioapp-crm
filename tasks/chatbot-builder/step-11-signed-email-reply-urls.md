# Step 11 — Signed email reply URL infrastructure

**Goal:** Enable Text Button / Media Button / List nodes to work over email by generating HMAC-signed, single-use, prefetch-safe reply URLs that record the customer's "click" as an inbound message on the correct conversation.
**Depends on:** Steps 1, 6, 7
**Status:** Pending

## Scope

**In-scope**
- `core/chatbots/signed_reply_urls.py` — signer + verifier + nonce store.
- Per-org HMAC key generation + storage (rotate-able).
- `GET /r/{signature}` — benign interstitial HTML page ("Confirm your reply: [Yes, submit]"). Mail-client prefetchers hit only this.
- `POST /r/{signature}` — records the "click" as an inbound message on the correct conversation; consumes the nonce; resumes the parked run.
- Prefetch defense: only the POST records the reply; GET is idempotent and never advances state.
- Expiry: 72h default (configurable per org).
- Single-use: nonce persisted in `tbl_chatbot_pending_replies` (Step 1); marked consumed on POST; second POST returns 410 Gone.
- Rate-limit the interstitial + POST endpoints to prevent enumeration.

**Out of scope**
- Landing page branding — reuses org login page theme (Decision §15).
- Sending the emails themselves — that's Step 7's Text Button email path (which reads Step 11's URL generator).

## Files to touch

- `API/src/app/core/chatbots/signed_reply_urls.py` (created)
- `API/src/app/core/chatbots/router.py` (modified — add public `GET /r/{sig}` and `POST /r/{sig}` endpoints; no auth required)
- `API/src/app/main.py` (modified — mount the `/r/*` routes at root, not under `/api/v1/chatbots/`)
- `API/src/app/core/settings/models.py` OR `tbl_organizations` (modified — add `chatbot_signed_url_key BYTEA`)
- `API/alembic/versions/0190_org_signed_url_key.py` (created)
- `API/src/app/templates/chatbot_reply_interstitial.html` (created — the confirmation page)
- `API/src/app/core/chatbots/nodes/text_button.py` / `list.py` (modified — use `signed_reply_urls.generate(...)` for email rendering)

## Plan

1. Migration `0190_org_signed_url_key` — adds an org-scoped 32-byte HMAC key column. Populate for existing orgs via `secrets.token_bytes(32)` in a data migration. Rotation is a follow-up.
2. `signed_reply_urls.py`:
   - `generate(org_id, run_id, node_id, button_id, contact_id) → (url, nonce)` — creates the nonce row in `tbl_chatbot_pending_replies` with 72h expiry; signs `(nonce, exp)` with the org's HMAC key; returns url `/r/{base64_signature}`.
   - `verify(signature) → (nonce_row | None)` — HMAC constant-time compare; expiry check; look up nonce row; return.
   - `consume(nonce)` — mark row `consumed_at = now`; race-safe via `UPDATE ... WHERE consumed_at IS NULL RETURNING`.
3. Router:
   - `GET /r/{sig}` — call `verify`; if invalid/expired/consumed → generic error page (no info leak). Else render the interstitial HTML page with a form POST to `/r/{sig}` and a button labeled after `button_id`'s label.
   - `POST /r/{sig}` — call `verify` + `consume` atomically; on success, create an inbound `Message` on the conversation with text = the button's label; publish `whatsapp.message_received` OR `email.message_received` as appropriate (the original bot run's channel); the trigger matcher / resume path picks it up. Return a "Thank you" HTML page.
4. Rate limit both endpoints via existing `slowapi` or in-memory bucket (Case: prevent nonce enumeration — 30 req/min per IP is plenty for a link-click flow).
5. Modify `text_button.py` + `list.py` — for email channel, render HTML with one signed URL per button/row.
6. Interstitial template — matches the login page theme (Decision §15); shows the button label, a "Confirm reply" primary button, and a "This will send a reply back to <org name>" caption. No conversation contents shown (Case #31).

## DB changes / migrations

`0190_org_signed_url_key` (24 chars) — adds byte column + data-migration populate. `tbl_chatbot_pending_replies` was pre-provisioned in Step 1.

## Tests to add

Location: `API/tests/core/chatbots/test_signed_reply_urls.py`

- `test_signed_url_generate_and_verify_round_trip`
- `test_signed_url_hmac_wrong_key_rejected`
- `test_signed_url_expired_rejected` (T18)
- `test_signed_url_single_use_second_post_returns_410` (T17)
- `test_signed_url_get_does_not_consume_nonce` (T19)
- `test_signed_url_prefetcher_simulation_no_reply_recorded` (T19)
- `test_signed_url_rate_limit_kicks_in`
- `test_signed_url_records_inbound_message_on_post`
- `test_signed_url_resumes_parked_run_via_matcher`
- `test_signed_url_hmac_constant_time_compare` — timing test if practical, else a code-review checkbox.

## Verification checklist

**Backend**
- [ ] Manual: build a bot with a Text Button node on email; test-fire; check the sent email HTML has 3 signed URLs; click one → interstitial → confirm → run advances.
- [ ] Manual: paste the signed URL twice; second paste shows "already used" error.
- [ ] Manual: modify signature by 1 char; GET returns generic error.
- [ ] Manual: check email prefetch simulation (`curl -X GET <url>` many times) — no reply recorded; nonce still consumable via POST.

**Frontend** — N/A this step (interstitial is server-rendered HTML).

**Code review**
- [ ] HMAC compare uses `hmac.compare_digest` (constant time).
- [ ] Nonce table has an index on `(nonce, org_id)` for fast lookup.
- [ ] Interstitial page reveals only the button label, not conversation content.
- [ ] GET is a `@router.get` with no side effects. POST is `@router.post` with idempotent-if-consumed behaviour.

## Self-check (10 rules)

- [ ] `core` didn't import `packs`
- [ ] `org_id` in every DB read/write (nonce table has org_id — enforce in verify)
- [ ] Sidebar/permissions N/A (public endpoints)
- [ ] Reuse — reuses existing FastAPI templating, existing rate-limiter middleware
- [ ] Zero TODOs

## Stop & report

Report the URL scheme, a sample generated URL (redact HMAC), the interstitial screenshot or HTML dump, and the timing of a full round-trip test. Await "proceed".
