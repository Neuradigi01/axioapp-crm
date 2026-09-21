# Track 2 Step 1 — Mailgun Domains API discovery

Per **DISCOVERY_RULES.md rule zero**: every factual claim below cites a URL
actually fetched in this session (2026-09-21). Public Mailgun docs
(documentation.mailgun.com, help.mailgun.com) returned 404 / 403 for most
API-reference paths — the docs site was reorganised. The primary source
is Mailgun's own **official PHP SDK** (`mailgun/mailgun-php`), which
serves as executable documentation of the API contract.

## Sources fetched

| Purpose | URL | Result |
|---|---|---|
| Domain API method endpoints | `https://raw.githubusercontent.com/mailgun/mailgun-php/master/src/Api/DomainV4.php` | ✅ Extracted method contracts |
| Domain response envelope | `https://raw.githubusercontent.com/mailgun/mailgun-php/master/src/Model/Domain/ShowResponse.php` | ✅ Extracted envelope fields |
| Domain body schema | `https://raw.githubusercontent.com/mailgun/mailgun-php/master/src/Model/Domain/Domain.php` | ✅ Extracted 15 fields |
| DNS record schema | `https://raw.githubusercontent.com/mailgun/mailgun-php/master/src/Model/Domain/DnsRecord.php` | ✅ Extracted 7 fields |
| Default US base URL | `https://raw.githubusercontent.com/mailgun/mailgun-php/master/src/Mailgun.php` | ✅ `https://api.mailgun.net` |
| EU base URL | (couldn't isolate to a single fetch — SDK's `create()` accepts arbitrary `$endpoint` param) | ⚠️ **UNVERIFIED** — see below |
| documentation.mailgun.com API refs | multiple attempts | ❌ 404 on all API-reference paths |
| help.mailgun.com DNS records article | tried | ❌ 403 |

## Locked facts (with sources)

### API version — **v4, not v3**

The official SDK ships `DomainV4.php` and issues requests to `/v4/domains/*`.
Our earlier plan notes referenced `/v3/domains/*` — this is corrected.
**All URLs in this track go to `/v4/`.**

Source: [DomainV4.php](https://raw.githubusercontent.com/mailgun/mailgun-php/master/src/Api/DomainV4.php).

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/v4/domains` | Create a new sending domain |
| GET | `/v4/domains/{name}` | Fetch a domain + its DNS records + current verification state |
| PUT | `/v4/domains/{name}/verify` | Force Mailgun to re-check DNS + return fresh state |
| DELETE | `/v4/domains/{name}` | Release the domain (irreversible per SDK docstring) |

### POST /v4/domains — request body

Fields the SDK sends (all optional except `name`):

- `name` (required) — the domain to claim
- `smtp_password` (optional)
- `spam_action` (optional)
- `wildcard` (optional, `"true"` or `"false"`)
- `force_dkim_authority` (optional)
- `ips` (optional, comma-separated IP list)
- `pool_id` (optional)
- `web_scheme` (optional, `"http"` or `"https"`, default `"http"`)
- **`dkim_key_size` (optional, `"1024"` or `"2048"`, default `"1024"`)**
- `dkim_host_name` (optional)
- `dkim_selector` (optional)
- `use_automatic_sender_security` (optional)

**Our v1 sends:** `name` + `dkim_key_size=2048` (upgraded from default 1024
for defense-in-depth). Everything else defaults.

### GET /v4/domains/{name} — response envelope

Top-level keys:

- `domain` — a Domain object (see below)
- `sending_dns_records` — array of DnsRecord (outbound SPF/DKIM/tracking)
- `receiving_dns_records` — array of DnsRecord (inbound MX — populated for
  routes-enabled domains)

Source: [ShowResponse.php](https://raw.githubusercontent.com/mailgun/mailgun-php/master/src/Model/Domain/ShowResponse.php).

### Domain object fields

| Field | Type | Purpose |
|---|---|---|
| `id` | string | Mailgun's domain UUID |
| `name` | string | The domain itself |
| `state` | string | Verification state (see below) |
| `type` | string | `"custom"` / `"sandbox"` / etc. |
| `created_at` | ISO timestamp | Domain creation at Mailgun |
| `smtp_login`, `smtp_password` | string | Programmatic SMTP creds |
| `wildcard` | bool | Wildcard-subdomain support |
| `spam_action` | string | `"disabled"` / `"tag"` / `"delete"` |
| `web_scheme` | string | `"http"` / `"https"` |
| `web_prefix` | string | Tracking-link scheme |
| `use_automatic_sender_security` | bool | Managed DKIM/SPF |
| `require_tls` | bool | TLS-only send policy |
| `skip_verification` | bool | Bypasses DNS verify (staging use) |
| `is_disabled` | bool | Domain disabled at Mailgun's side |

**We store fields `id`, `name`, `state`, `type`, and the whole
`sending_dns_records` + `receiving_dns_records` arrays in our JSONB
`dns_records` column verbatim.** Everything else can be re-fetched
on demand.

Source: [Domain.php](https://raw.githubusercontent.com/mailgun/mailgun-php/master/src/Model/Domain/Domain.php).

### DnsRecord schema — the critical shape

Every entry in `sending_dns_records[]` and `receiving_dns_records[]`
has these fields (each nullable — Mailgun sometimes omits fields per
record type):

| Field | Type | Example |
|---|---|---|
| `record_type` | string | `"TXT"`, `"CNAME"`, `"MX"` |
| `name` | string | The hostname (e.g. `smtp._domainkey.acme.com`) |
| `value` | string | The record value / target |
| `priority` | string | Populated only for MX records (`"10"`) |
| `valid` | string | `"valid"` when Mailgun sees the record; otherwise other verdict values |
| `cached` | array | Current observed DNS value(s) |
| `is_active` | bool | Whether this record is currently enforced |

**Format-shape note vs the SES screenshot the user shared:** SES returns
**3 CNAMEs** for DKIM (`<token>._domainkey.acme.com` → `<token>.dkim.amazonses.com`).
**Mailgun returns TXT records** for DKIM (the public key embedded
in the `value` field). Our UI must render the JSONB verbatim — no
CNAME-vs-TXT normalisation.

Source: [DnsRecord.php](https://raw.githubusercontent.com/mailgun/mailgun-php/master/src/Model/Domain/DnsRecord.php).

### PUT /v4/domains/{name}/verify

Instructs Mailgun to re-check the domain's DNS. Returns a fresh
domain envelope (same shape as GET) with updated `state` + `valid`
flags per DNS record.

### DELETE /v4/domains/{name}

Removes the domain from Mailgun. **Irreversible** per SDK docstring.
Callers should confirm before firing.

### Regional base URLs

| Region | Base URL | Source |
|---|---|---|
| **US (default)** | `https://api.mailgun.net` | ✅ Verified from [Mailgun.php](https://raw.githubusercontent.com/mailgun/mailgun-php/master/src/Mailgun.php) — `create()` method's default `$endpoint` param |
| **EU** | `https://api.eu.mailgun.net` | ⚠️ **UNVERIFIED in this session** — SDK's `create()` accepts arbitrary `$endpoint` and doesn't hard-code an EU URL. This is the widely-known Mailgun EU host, but before wiring EU-region tenants in production, an operator must confirm from Mailgun's account dashboard (Domains → Region selector shows the exact API host per region). |

**Implication for our client:** `MAILGUN_REGION` env var + a per-domain
`region` column drives base-URL selection. Ship the US path first;
EU-region domains stay dormant until the URL is confirmed.

## Facts we still lack (flagged as open)

1. **Exact response body of POST /v4/domains** — the SDK's `CreateResponse`
   class wasn't fetched. We assume it mirrors the GET envelope (Domain +
   sending_dns_records + receiving_dns_records). If POST returns a
   truncated shape, we'll re-fetch via GET immediately after create.
2. **Exact response body of PUT /verify** — same assumption; verified at
   implementation time in Step 2 or 3.
3. **`state` enum values** — the SDK doesn't enumerate. Widely known:
   `"unverified"`, `"active"`, `"disabled"` — but our own
   `verification_status` column uses our own state machine
   (`pending → verified → demoted → released`), sourced from the boolean
   `valid` flags per DNS record aggregated across the array. Mailgun's
   `state` is stored in JSONB for audit, not used as the state-machine truth.
4. **Rate limits on POST /v4/domains** — no fetch source. Mailgun account
   dashboards typically show account-wide domain quotas. Track 4
   (reputation + warmup) will re-fetch this alongside the rate-limit
   endpoint discovery.

## JSONB `dns_records` schema — locked

Given the fetched DnsRecord shape, our JSONB column stores:

```jsonc
{
  "sending": [
    {
      "record_type": "TXT",
      "name": "smtp._domainkey.acme.com",
      "value": "v=DKIM1; k=rsa; p=...",
      "priority": null,
      "valid": "valid",
      "cached": [],
      "is_active": true
    }
    /* ...more records */
  ],
  "receiving": [
    /* same shape */
  ]
}
```

Populated **verbatim** from Mailgun's response. The frontend renders each
entry as a card without any transformation.

## Kept-vs-dropped from earlier plan

- **Kept:** state machine (`pending → verified → demoted → released`),
  nightly + hourly re-verify cadence, per-domain `region` column,
  `EMAIL_DOMAIN_DEMOTE_AFTER_FAILED_CHECKS` + `EMAIL_DOMAIN_RELEASE_AFTER_FAILED_DAYS`.
- **Corrected:** URL path is `/v4/domains/*`, not `/v3/domains/*`.
- **Verified:** DNS records are Mailgun-format (TXT-heavy), not SES-format
  (3-CNAME DKIM).
- **Held provisional:** EU base URL string (widely-known but not
  confirmed in this session).
