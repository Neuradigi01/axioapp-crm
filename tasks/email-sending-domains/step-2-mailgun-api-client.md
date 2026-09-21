# Step 2: Mailgun API client wrapper

**Status:** Pending

## Goal

One seam that speaks to Mailgun's domain-management endpoints — regional routing, timeout, retry-on-5xx, signed with `MAILGUN_API_KEY`. Every downstream service goes through this wrapper.

## Files touched

- `api/src/app/core/email/mailgun/api_client.py` — new client
- `api/src/app/core/email/mailgun/api_client_errors.py` — exception classes
- `api/tests/test_mailgun_api_client.py`

## What this step does

- `MailgunApiClient` class:
  - Constructor: `region: str = 'us'` — base URL `https://api.mailgun.net/v3` for `us`, `https://api.eu.mailgun.net/v3` for `eu`.
  - Auth: HTTP basic `("api", MAILGUN_API_KEY)`.
  - Timeout: hard 10s per request (`httpx.Timeout(10.0)`).
  - Retry: on 502/503 only, up to 2 retries, exponential backoff 0.5s → 1s. Never retries 4xx.
  - Methods:
    - `create_domain(domain: str, dkim_key_size: int = 1024) -> DomainCreateResult` → POST `/domains`
    - `get_domain(domain: str) -> DomainDetail` → GET `/domains/{domain}` — returns raw response body + parsed fields
    - `delete_domain(domain: str) -> None` → DELETE `/domains/{domain}` (idempotent 404-ok)
    - `verify_domain(domain: str) -> DomainDetail` → PUT `/domains/{domain}/verify` (Mailgun re-checks DNS + returns fresh state)
- Exception classes: `MailgunAuthError` (401), `MailgunNotFound` (404), `MailgunRateLimited` (429), `MailgunProviderError` (5xx after retries), `MailgunResponseInvalid` (JSON shape wrong).
- Return types (Pydantic models) carry: `mailgun_domain_id`, `state`, `sending_dns_records: list[dict]` (verbatim from Mailgun), `receiving_dns_records: list[dict]`, `created_at`.

## Tests

- `test_client_base_url_switches_on_region`
- `test_client_uses_basic_auth_with_api_key`
- `test_client_timeout_10s`
- `test_client_retries_on_502_503_only`
- `test_client_does_not_retry_4xx`
- `test_client_raises_MailgunAuthError_on_401`
- `test_client_raises_MailgunNotFound_on_404`
- `test_client_raises_MailgunResponseInvalid_on_bad_json`
- `test_create_domain_returns_parsed_result_with_verbatim_records`
- `test_get_domain_returns_records_verbatim_from_provider`
- `test_delete_domain_404_treated_as_success`

## Verification checklist

- [ ] All 11 tests pass (mocked httpx client)
- [ ] Pin-tests pass
- [ ] Ruff clean

## Self-check

- Rule 10: pass.
- Layered: pass — this is a shared helper called from service layer.
- Reuse: pass — future WhatsApp/Meta clients follow same shape but don't share code (different auth).

## Stop-and-report

Report file count, test pass. **Awaiting your "proceed" for Step 3.**
