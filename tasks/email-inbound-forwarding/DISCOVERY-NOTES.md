# Discovery notes — email-inbound-forwarding Step 1

**Session:** 2026-09-21. Timebox: 2 hours.

Every factual claim in the sibling [`PROVIDER-GUIDES.md`](PROVIDER-GUIDES.md) traces back to one of the URLs in the **Fetched** table below. **Nothing in this discovery pass is recalled from memory** (per [`DISCOVERY_RULES.md`](../../DISCOVERY_RULES.md) rule zero). Where a URL didn't resolve or a source is missing, it is flagged in the **Gaps** section rather than paved over.

## Fetched — URLs that returned content this session

| # | Purpose | URL | Verdict |
|---|---|---|---|
| 1 | Gmail personal — auto-forwarding | https://support.google.com/mail/answer/10957 | ✅ Full step list |
| 2 | Google Workspace — recipient-address-map routing | https://knowledge.workspace.google.com/admin/gmail/advanced/redirect-or-forward-gmail-messages-to-another-user (redirected from `support.google.com/a/answer/4524505`) | ✅ Full step list |
| 3 | Exchange Server — mail-flow rules (rule anatomy, priority, storage, agents) | https://learn.microsoft.com/en-us/exchange/policy-and-compliance/mail-flow-rules/mail-flow-rules | ✅ Full concept doc |
| 4 | Exchange Online / Microsoft 365 — mail-flow best practices (MX, SPF, DKIM, DMARC context) | https://learn.microsoft.com/en-us/exchange/mail-flow-best-practices/mail-flow-best-practices | ✅ Overview only (see gap #2) |
| 5 | Zoho Mail — email forwarding | https://www.zoho.com/mail/help/email-forwarding.html | ✅ Full step list |

## Gaps — URLs the step spec listed but that did NOT return content this session

1. **Mailgun Routes documentation.** The step-1 spec cited `https://documentation.mailgun.com/en/latest/user_manual.html#routes`. That URL now returns only Mailgun's high-level "Features Overview" — the actual Routes reference (filter expressions, action syntax, priority semantics, regex flavour) is not in the response. Fallback URLs also failed:
   - `https://documentation.mailgun.com/docs/mailgun/user-manual/routes/` → 404
   - `https://documentation.mailgun.com/docs/mailgun/user-manual/routes` → 404
   - `https://documentation.mailgun.com/docs/mailgun/api-reference/openapi-final/tag/Routes/` → 404
   - `https://documentation.mailgun.com/en/latest/api-routes.html` → 404
   - `https://help.mailgun.com/hc/en-us/articles/202256730-How-do-I-create-a-Route-` → 403 (Zendesk CDN block)
   - `https://api.mailgun.net/v3/routes` → 401 (endpoint alive, no docs served)
   - `https://web.archive.org/...` → blocked by client

   **Source-of-truth fallback:** the shipped `tasks/mailgun-inbound` track ran this exact API against a live Mailgun sandbox during its Step 7 smoke — see [`API/src/app/scripts/mailgun_route_setup.py`](../../API/src/app/scripts/mailgun_route_setup.py) + [`tasks/mailgun-inbound/SMOKE-RESULTS.md`](../mailgun-inbound/SMOKE-RESULTS.md). Those files pin the Routes API contract as observed in production. [`PROVIDER-GUIDES.md`](PROVIDER-GUIDES.md) references them for the Mailgun section rather than paraphrasing memory of the (unreachable) docs.

2. **Outlook.com personal — auto-forwarding.** Every URL variation for the personal-account Outlook forwarding guide 404'd or redirected in a loop:
   - `https://support.microsoft.com/en-us/office/turn-on-automatic-forwarding-in-outlook-com` → 404
   - `https://support.microsoft.com/en-us/office/enable-automatic-forwarding-in-outlook-com-eb1c766f-9d34-4a4e-b8c2-a35608c53f60` → 404
   - `https://support.microsoft.com/en-us/office/forward-email-from-outlook-com-to-another-email-account-…` (several variations) → 404
   - `https://prod.support.services.microsoft.com/…` → 301 redirects back to the 404ing `support.microsoft.com` URL

   Microsoft appears to have relocated the personal Outlook.com forwarding article. **Flagged for user to paste the current URL or a screenshot of the current in-product Settings → Forwarding pane.** Without that, the personal-Outlook branch of [`PROVIDER-GUIDES.md`](PROVIDER-GUIDES.md) carries a **`TBD — URL missing`** placeholder rather than a synthesized step list.

3. **Custom IMAP / Sieve rule for forwarding.** No single canonical URL — the "server-side Sieve rule" flow is described across cPanel docs, RFC 5228, and Fastmail's Sieve editor. This is a niche cohort (< 5 % of expected wizard users based on the HubSpot / Front benchmark). Flagged for a **manager decision**: do we ship this branch at all, or gate to "if your provider isn't listed, reach out to support"? Deferring the URL fetch until that call is made.

## Wizard-shape benchmarks — screenshot shopping list

The step-1 spec noted the HubSpot / Front / Missive wizard shapes are "unsourced initially; verify by screenshot request from user." I did not attempt to fetch these because those wizards live behind login. **User action:**

1. **HubSpot Shared Inbox — Connect a channel → Forwarding.** Screenshots: (a) provider picker step, (b) copy-address step, (c) provider-guide + test-send step.
2. **Front — Add channel → IMAP-connect vs forwarding decision.** Screenshot: the channel-add modal's provider list.
3. **Missive — Add mailbox → forwarding path.** Screenshot: single-guide-page shape (spec claim to verify).

Once received these will land in a `WIZARD-BENCHMARKS.md` sibling doc. Until then, [`PROVIDER-GUIDES.md`](PROVIDER-GUIDES.md) uses only the fetched provider content — the wizard **content** is decided, but the wizard **shape** (single-page vs stepped) stays open.

## Mailgun Routes semantics — pinned by shipped code, not by fetched docs

Since gap #1 blocks the doc-fetch, this section pins the Routes contract as it currently ships in `tasks/mailgun-inbound`. Any drift in a future doc fetch supersedes this.

**API base:** `https://api.mailgun.net/v3` — from [`mailgun_route_setup.py`:45](../../API/src/app/scripts/mailgun_route_setup.py#L45).

**Filter expression:** `match_recipient("<regex>")`. The regex escapes dots (`domain.replace(".", r"\.")`) — the shipped code uses Python-style character-class escapes, and Mailgun's API accepted it in live production during the Step 7 smoke. See [`mailgun_route_setup.py`:99-104](../../API/src/app/scripts/mailgun_route_setup.py#L99-L104).

**Action expression:** an ARRAY of strings, each a function call. The shipped route uses `[f'forward("{webhook_url}")', "stop()"]` — forward posts the payload, `stop()` prevents fall-through to lower-priority routes. See [`mailgun_route_setup.py`:107-111](../../API/src/app/scripts/mailgun_route_setup.py#L107-L111).

**Route payload shape:** `{priority: int, description: str, expression: str, action: list[str]}`. Priority `0` is the highest (fires first). Lower priority means "later in the chain". See [`mailgun_route_setup.py`:140-146](../../API/src/app/scripts/mailgun_route_setup.py#L140-L146).

**List pagination:** `GET /v3/routes?limit=1000` — Mailgun caps `limit` at 1000. See [`mailgun_route_setup.py`:119-121](../../API/src/app/scripts/mailgun_route_setup.py#L119-L121).

**Priority + stop() semantics:** the shipped code's comment says `stop()` "prevents Mailgun's implicit fall-through to any lower-priority route" — meaning without `stop()`, Mailgun executes matching lower-priority routes too. See [`mailgun_route_setup.py`:108-110](../../API/src/app/scripts/mailgun_route_setup.py#L108-L110).

**Confirmation for Step 1 verification checklist item "existing catch-all handles `f-*` prefix":** the shipped `match_recipient(".*@<MAILGUN_DOMAIN>")` filter matches every local part at the inbound domain (regex `.*@`), so `in_<token>@` (mailgun-inbound track) and `f-<token>@` (this track) both fire the same route without adding a new one. Step 2 of this track's ingest task discriminates by local-part prefix at the Python side. Confirmed by the regex shape — no new Mailgun-side route needed.

## Open questions for Step 2 planning

1. **Outlook.com personal step list.** Blocked on gap #2 until user supplies a URL or screenshot.
2. **Custom IMAP / Sieve branch.** Ship or defer to "contact support"? Manager call.
3. **Wizard shape (single-page vs 3-step).** Blocked on gap #3 until user supplies HubSpot / Front / Missive screenshots.
4. **Google Workspace: DKIM re-signing on forwarded copies.** The Google Workspace doc fetched here doesn't cover it. **Recommend a follow-up fetch of `https://support.google.com/a/answer/10685501` (SPF / DKIM impact of Workspace forwarding)** during Step 2 planning.
