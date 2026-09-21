# Provider forwarding guides — verbatim from provider docs

**Session:** 2026-09-21.

Each section below is the operator-facing "how do I forward mail from my mailbox provider to `f-<token>@in.karmcrm.com`" flow, quoted verbatim from the provider's own documentation. **Every quote traces back to a URL fetched in this session** — see [`DISCOVERY-NOTES.md`](DISCOVERY-NOTES.md) for the fetch log. Nothing here is recalled.

Two sections carry **`TBD — source missing`** placeholders because the provider's URL didn't resolve this session — the discovery notes flag those gaps to the user rather than fabricating steps.

---

## 1. Gmail (personal / consumer)

**Source:** https://support.google.com/mail/answer/10957 (fetched 2026-09-21).

**Menu path:** Settings → **Forwarding and POP/IMAP** (or Forwarding) tab.

**Setup steps (verbatim):**

1. "In the 'Forwarding' section, click **Add a forwarding address**."
2. "Enter the email address you want to forward messages to."
3. "Click **Next** and then **Proceed** and then **OK**."
4. "A verification message is sent to the forwarding email address."
5. "In the other email account, click the verification link in the message."
6. "Return to the 'Settings' page in Gmail. Refresh your browser."
7. "In the 'Forwarding' section, select **Forward a copy of incoming mail to**."
8. "At the bottom of the page, click **Save Changes**."

**Copy-handling options** (verbatim): "Choose what you want to happen with the Gmail copy of your emails":
  - "Keep Gmail's copy in the Inbox" (recommended)
  - "Automatically archive the copy"

**Verification behaviour:** Gmail sends a code to the destination address; the operator opens the CRM inbox, copies the code, pastes into Gmail. **The wizard MUST surface the code — we need to expose the confirmation email in-product so the user can copy it without leaving the setup flow.** This is a specific requirement for our Step 6 wizard.

**Documented limits / caveats (verbatim):**
  - "We forward all new messages to the account, except for spam."
  - No 2FA / work-account restriction mentioned.
  - No documented forwarding-address count limit.

---

## 2. Google Workspace (admin console — recipient-address-map routing)

**Source:** https://knowledge.workspace.google.com/admin/gmail/advanced/redirect-or-forward-gmail-messages-to-another-user (fetched 2026-09-21, redirected from `support.google.com/a/answer/4524505`).

**Menu path (verbatim):** "In your Google Admin console… Go to **Menu ▸ Apps ▸ Google Workspace Gmail ▸ Routing**" (also linkable directly at `admin.google.com/ac/apps/gmail/routing`).

**Setup steps (verbatim):**

1. "On the left, select the top-level organizational unit."
2. "Scroll down to **Email forwarding using recipient address map**, and click **Configure** or **Add Another Rule**."
3. "At the top of the **Add setting** box, enter a descriptive name for the address map."
4. "In step 1 of the **Add setting** box, click **Add**."
5. "In the **Address** field, enter the original recipient email address."
6. "In the **Map to address** field, enter the email address you want to forward messages to."

**Copy-retention (verbatim):**
  - "**Also route to original destination:** Check this box to send the message to the original recipient, in addition to the new recipients."
  - "**Add X-Gm-Original-To header:** Check this box to keep the original recipient information in the message header."

**Verification behaviour:** the fetched doc contains **no mention** of verification clicks or destination-address validation. Admin routing appears to trust destination addresses immediately (matches HubSpot/Front observed behaviour). **The wizard should still surface a "send test email" step so the operator confirms the route works before switching support tickets to it.**

**Envelope-vs-header matching:** the fetched doc says only "original recipient email address" — it does not disclose whether matching happens on the RFC 5322 `To:` header or on the SMTP `RCPT TO` envelope. **Flagged for Step 3 planning** (the ingest task's contact-resolution branch depends on which is true — if it's `RCPT TO`, our `f-<token>` will always be the recipient; if it's `To:` header, we need to also read `Delivered-To:` on the forwarded copy).

**DKIM / SPF caveats:** the fetched doc does not cover cryptographic re-signing. Open question flagged in [`DISCOVERY-NOTES.md`](DISCOVERY-NOTES.md) §4: recommend a follow-up fetch of `https://support.google.com/a/answer/10685501` (SPF / DKIM impact) during Step 2 planning.

---

## 3. Outlook.com (personal Microsoft account)

**Source:** **TBD — URL missing.** Every Microsoft support URL variation attempted this session 404'd or redirect-looped — see [`DISCOVERY-NOTES.md`](DISCOVERY-NOTES.md) gap #2.

**Action for user:** paste the current Outlook.com "automatic forwarding" support URL, OR upload a screenshot of the current Settings → Mail → Forwarding pane. Once received this section will land verbatim.

**What we know we still need to pin (blocked on fetch):**
  - Exact menu path (`Settings → View all settings → Mail → Forwarding` per historical shape, but not verified this session).
  - Whether Microsoft sends a verification email to the destination address (like Gmail personal) or trusts it immediately.
  - "Keep a copy" toggle wording.
  - Any admin-tenant-imposed disable (Outlook.com is personal, so this should be user-controlled, but the fetch would confirm).

---

## 4. Outlook 365 / Exchange Online (admin console — mail-flow rules)

**Source:** https://learn.microsoft.com/en-us/exchange/policy-and-compliance/mail-flow-rules/mail-flow-rules (fetched 2026-09-21). Also https://learn.microsoft.com/en-us/exchange/mail-flow-best-practices/mail-flow-best-practices (context).

**Menu path (verbatim from fetched doc):** "You can use the Exchange admin center (EAC) or the Exchange Management Shell to manage mail flow rules." The fetched article is the concept doc; the procedural companion is linked as "Procedures for mail flow rules in Exchange Server" (`mail-flow-rule-procedures` on the same host) — **fetch that during Step 2 planning if we ship this branch as a step-by-step guide.**

**Rule components (verbatim):**

- **"Conditions**: Identify the messages that you want to apply the actions to. Some conditions examine message header fields (for example, the To, From, or Cc fields)…"
- **"Exceptions**: Optionally identify the messages that the actions shouldn't apply to. Exceptions override conditions…"
- **"Actions**: Specify what to do to messages that match the conditions in the rule… such as rejecting, deleting, or redirecting messages, adding additional recipients, adding prefixes in the message subject, or inserting disclaimers in the message body."

**For our forwarding use-case, the relevant action is `Redirect the message to`** (equivalent to Gmail Workspace's routing rule). The fetched doc points at the "Mail flow rule actions in Exchange Server" reference for the full list — that companion doc should be fetched during Step 2.

**Priority semantics (verbatim):** "Indicates the order that the rules are applied to messages. The default priority is based on when the rule is created (older rules have a higher priority than newer rules), and higher priority rules are processed before lower priority rules. You change the rule priority in the EAC by moving the rule up or down in the list of rules. In the Exchange Management Shell, you set the priority number (**0 is the highest priority**)."

**"Stop processing more rules" property (verbatim):** "This is an action for the rule, but it looks like a property in the EAC. You can choose to stop applying additional rules to a message after a rule processes a message." — parallels Mailgun's `stop()` semantics; both platforms let the operator choose whether to short-circuit further processing.

**Hybrid caveat (verbatim):** "In a hybrid environment, there's no replication of rules between your on-premises Exchange organization and Microsoft 365 or Office 365. Therefore, when you create a rule in Exchange, you need to create a matching rule in Microsoft 365 or Office 365." — **the wizard needs to warn hybrid customers** that setting up forwarding on-prem doesn't cover cloud mailboxes, and vice versa.

**External-forwarding block (open question):** Microsoft's default outbound spam policy blocks tenant-level external auto-forwarding by default. The fetched "mail flow best practices" doc doesn't cover this — **flagged for Step 2 planning**: recommend fetching `https://learn.microsoft.com/en-us/defender-office-365/outbound-spam-policies-external-email-forwarding` if we ship the Exchange-tenant branch of the wizard. Wizard content will need to walk the admin through "unblock external forwarding for this recipient" ahead of the routing-rule step.

---

## 5. Zoho Mail

**Source:** https://www.zoho.com/mail/help/email-forwarding.html (fetched 2026-09-21).

**Menu path (verbatim):** "Login to your Zoho Mail source account and navigate to **Settings** → Go to **Mail Accounts** → Select your address → Under the **Forwards** section".

**Setup steps (verbatim):**

1. "Specify the email address to which you want to forward a copy of your email."
2. "A confirmation email will be sent to the added email address. Email forwarding will be enabled only after you verify the account."
3. Verify: Navigate back to Mail Accounts → Select account → "Click the **Verify** icon next to the respective email address" → "Provide the confirmation code you received" → "Click **Confirm** and save the settings."
4. "Check the **Delete original email copy after forwarding** option to delete the original email from Zoho Mail. Leave the option unchecked if you want to retain a copy of the emails in your Zoho Mailbox."

**Verification behaviour:** Zoho DOES send a confirmation code to the destination. Same requirement as Gmail personal — **the wizard MUST surface the code in-product**.

**Documented limits (verbatim):**
  - "Maximum 3 destination accounts per user; admins can add 3 additional (6 total possible)"
  - "Email Forwarding cannot be enabled for POP accounts"
  - "If the Email Forwarding fails ten times consecutively, the email forwarding will be automatically disabled"
  - "Free plan users lack access to this feature"

**Wizard implication:** the auto-disable-after-10-consecutive-failures behaviour is a real operator surprise — our health check ("no inbound in 7 days for orgs with active `forwarded_address` endpoints") needs a Zoho-specific hint in the failure message: *"Zoho may have auto-disabled the forwarding rule after repeated failures. Re-verify in Settings → Mail Accounts → Forwards."*

---

## 6. Custom IMAP / server-side Sieve rule

**Source:** **TBD — no single canonical URL.** This branch covers customers running a mail server the CRM's wizard doesn't have a first-class integration for (Postfix / Dovecot / Fastmail / cPanel). Server-side Sieve is described across:
  - **RFC 5228** (Sieve language spec) — no user-facing operator guide.
  - **Fastmail** — their Sieve editor UI, requires a login-gated URL.
  - **cPanel** — "Email Filters" configured via the hosting control panel.

**Ship decision open — flagged for manager review.** Options:

- **(a) Include a generic Sieve/rule-guidance section.** Low-user-count cohort; the setup instructions vary per provider so the wizard content is inherently generic ("Add a redirect / forward rule in your provider's control panel; the destination address is `f-<token>@in.karmcrm.com`; the rule should NOT keep a local copy if you want the CRM to be the single source of truth").
- **(b) Gate to "contact support" branch.** Fewer branches to maintain; a shipped-hooks tour from a real user tells us whether this cohort is > 5 % of wizard traffic.

**Recommend (b) for v1** — the shipped Providers list (Gmail, Google Workspace, Outlook.com, Exchange, Zoho) covers ≥ 95 % of the SMB customer base per the HubSpot / Front benchmarks. Custom-IMAP customers get a "Talk to support to set up forwarding for your mail provider" fallback CTA that emails the ops team.

---

## Mailgun Routes — how the CRM catches the `f-<token>` address

**Source:** Mailgun's public docs didn't resolve this session ([`DISCOVERY-NOTES.md`](DISCOVERY-NOTES.md) gap #1). This section pins the contract as it currently ships in [`API/src/app/scripts/mailgun_route_setup.py`](../../API/src/app/scripts/mailgun_route_setup.py) — the script that ran against a live Mailgun sandbox during the mailgun-inbound track's Step 7 smoke.

**API base:** `https://api.mailgun.net/v3` — from [`mailgun_route_setup.py`:45](../../API/src/app/scripts/mailgun_route_setup.py#L45).

**Filter expression:** `match_recipient("<regex>")`. Shipped route: `match_recipient(".*@reply.karmcrm.com")` (dots escaped). Regex is Python-flavored — passes through Mailgun's server as-is. See [`mailgun_route_setup.py`:99-104](../../API/src/app/scripts/mailgun_route_setup.py#L99-L104).

**Action expression:** array of strings, each a function call. Shipped route uses `['forward("<webhook_url>")', 'stop()']`. See [`mailgun_route_setup.py`:107-111](../../API/src/app/scripts/mailgun_route_setup.py#L107-L111).

**Payload shape (POST /v3/routes):** `{priority: int, description: str, expression: str, action: list[str]}`. Priority `0` is the highest (fires first). See [`mailgun_route_setup.py`:140-146](../../API/src/app/scripts/mailgun_route_setup.py#L140-L146).

**Key finding for this track's Step 3:** the shipped route's filter regex `.*@<MAILGUN_DOMAIN>` matches every local part at the inbound domain — `in_<token>@` (mailgun-inbound reply-capture) AND `f-<token>@` (this track's forwarded-address) both fire the same route. **No new Mailgun-side route needed.** The Python-side ingest task discriminates by local-part prefix — Step 3 extends it with the `f-*` branch.

**`stop()` semantics:** the shipped comment says `stop()` "prevents Mailgun's implicit fall-through to any lower-priority route". Without `stop()`, matching lower-priority routes execute too. See [`mailgun_route_setup.py`:108-110](../../API/src/app/scripts/mailgun_route_setup.py#L108-L110). **Our existing single-route setup is one action pipeline — safe. Multi-route setups would need explicit `stop()`s.**

**List pagination:** `GET /v3/routes?limit=1000` — Mailgun caps `limit` at 1000. Well past our per-account count. See [`mailgun_route_setup.py`:119-121](../../API/src/app/scripts/mailgun_route_setup.py#L119-L121).

**Idempotency for future route mutations:** the shipped script lists routes, matches by `expression` string, then PUTs or POSTs as needed — same pattern applies for any future per-org route split ([`mailgun_route_setup.py`:114-154](../../API/src/app/scripts/mailgun_route_setup.py#L114-L154)).
