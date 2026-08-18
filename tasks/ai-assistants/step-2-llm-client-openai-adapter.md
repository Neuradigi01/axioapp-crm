# Step 2 — LLM client interface + OpenAI adapter (`shared/llm/`)

**Goal:** Ship the provider-agnostic `LLMClient` interface and one OpenAI adapter with `base_url` hardcoded (SSRF defence). Typed exception classes. Server-side usage extraction. No streaming caller yet — that lands in Step 9's chat runtime; this step ships `.complete()` returning a full response and `.stream()` returning an async iterator, both against a real OpenAI mock.
**Status:** Pending
**Depends on:** Step 1 (needs `AiProviderKeyRepo` for key-id → decrypted-key resolution).

---

## Scope

In-scope:

- `shared/llm/__init__.py` — exports the factory: `def factory(provider: str, key_id: UUID) -> LLMClient`.
- `shared/llm/base.py` — the `LLMClient` protocol:
  - `async def complete(messages, model, temperature=0.5, max_tokens=1024) -> LLMResponse`
  - `async def stream(messages, model, temperature=0.5, max_tokens=1024) -> AsyncIterator[LLMChunk]`
  - `async def probe() -> ProbeResult` — a cheap 1-token completion used by the test endpoint (Step 1's `test_provider_key`).
  - `async def embed(texts: list[str], model: str = 'text-embedding-3-small') -> list[list[float]]` — used by Step 10's ingest.
- `shared/llm/errors.py` — `ProviderError` (base), `ProviderAuthError` (401), `ProviderQuotaExceeded` (429), `ProviderTimeout`, `ProviderBadRequest`, `ProviderServerError`. All carry `provider`, `status_code`, `request_id` (from response headers).
- `shared/llm/openai.py` — the adapter:
  - Reads the decrypted key via `core.integrations.ai.service.decrypt_provider_key(db, key_id)`.
  - **Hardcoded `base_url="https://api.openai.com/v1"`** — no way to override, no `base_url` in the client constructor signature.
  - `AsyncOpenAI(api_key=..., base_url=<HARDCODED>, timeout=30.0)` — timeout enforced.
  - Passes `messages`, `model`, `temperature`, `max_tokens`; response `usage` field extracted for cost tracking (`prompt_tokens`, `completion_tokens`, `total_tokens`).
  - Maps OpenAI SDK exceptions → our typed exceptions.
  - `probe()` calls `models.list()` (cheap; verifies auth without token spend) — falls back to a 1-token completion if the org's key has `models.list` scoped out.
  - `embed()` calls `embeddings.create(model, input=texts)`; batch-size clamped at 100 per call (OpenAI limit).
- Pricing table `shared/llm/pricing.py` — hardcoded `{model: (prompt_usd_per_1k, completion_usd_per_1k, embedding_usd_per_1k_tokens)}` for `gpt-4o`, `gpt-4o-mini`, `gpt-4-turbo`, `gpt-3.5-turbo`, `text-embedding-3-small`. `cost_for(usage, model)` returns USD.
- Convention pin-test [API/tests/test_llm_adapter_boundary.py](API/tests/test_llm_adapter_boundary.py) — grep-based: `openai` import allowed ONLY in `shared/llm/openai.py`. Any other module importing `openai` fails CI.

Out of scope:
- Non-OpenAI adapters (deferred).
- Anthropic / Google / OpenRouter (deferred).
- The `AiProviderKey.reassign` UPDATE (Step 5).
- Any tool/function-calling shape (deferred).

## Files to touch

| File | Action |
|---|---|
| `API/src/app/shared/llm/__init__.py` | **NEW** — factory export |
| `API/src/app/shared/llm/base.py` | **NEW** — LLMClient protocol + response dataclasses |
| `API/src/app/shared/llm/errors.py` | **NEW** |
| `API/src/app/shared/llm/openai.py` | **NEW** |
| `API/src/app/shared/llm/pricing.py` | **NEW** |
| `API/pyproject.toml` | **EDIT** — add `openai>=1.50` dependency |
| `API/src/app/core/integrations/ai/service.py` | **EDIT** — wire Step 1's `test_provider_key` to call `factory('openai', key_id).probe()` |
| `API/tests/shared/llm/test_openai_adapter.py` | **NEW** — using `pytest-httpx` or `respx` to mock OpenAI |
| `API/tests/test_llm_adapter_boundary.py` | **NEW** — grep pin-test |

**~9 files. ~400 lines.**

## Plan

1. Base protocol first — `LLMResponse` dataclass (`content: str`, `usage: Usage`, `model: str`, `finish_reason: str`); `LLMChunk` dataclass (`delta: str`, `usage: Usage | None`, `finish_reason: str | None`).
2. Errors — map `openai.AuthenticationError` → `ProviderAuthError`; `openai.RateLimitError` → `ProviderQuotaExceeded`; `openai.APITimeoutError` → `ProviderTimeout`; `openai.BadRequestError` → `ProviderBadRequest`; `openai.APIError` → `ProviderServerError`.
3. Adapter — constructor takes `db: Session, key_id: UUID`; lazy-decrypts on first call. Client instance memoised per-adapter-instance.
4. Pricing — computed server-side from OpenAI's `response.usage`. Widget-reported usage never trusted (belt + braces for Step 15).
5. Wire Step 1's `test_provider_key` to `factory('openai', key_id).probe()`; catch `ProviderAuthError` → `test_status='failed'` with a friendly error message.
6. Pin-test — walks every `.py` under `src/app/` (excluding `shared/llm/openai.py`), rejects any `import openai` or `from openai`.

## DB changes / migrations

None.

## Tests

- `LLMClient.complete()` on a mocked 200 response returns `LLMResponse` with correct usage + content.
- `stream()` iterates chunks correctly (mock a chunked SSE-style response).
- `ProviderAuthError` raised on mocked 401.
- `ProviderQuotaExceeded` raised on mocked 429.
- `ProviderTimeout` raised when mock exceeds 30s.
- `openai` import is NOT accepted in a caller file: create a test file with `import openai` and assert the pin-test fails on it (the pin-test verifies its own detection).
- Adapter constructor does NOT accept `base_url` / `organization` / `custom_headers` kwargs: `pytest.raises(TypeError)`.
- `embed()` batches 250 inputs into 3 calls (100 + 100 + 50).
- Pricing: `cost_for(usage={"prompt_tokens": 1000, "completion_tokens": 500}, model="gpt-4o-mini")` returns the arithmetic result from the pricing table.

## Smoke

```
1. Set AI_PROVIDER_KEY_KEK. Add a valid OpenAI key via Step 1's POST endpoint.
2. curl POST /integrations/ai/providers/{id}/test → test_status='success' (real OpenAI call).
3. Python REPL:
   from shared.llm import factory
   c = factory('openai', key_id)
   r = await c.complete([{"role":"user","content":"Say hi"}], model="gpt-4o-mini")
   print(r.content, r.usage)
```

## Risks

- The pin-test grepping is text-based; it could false-positive on a comment `# import openai here`. Mitigation: strip comments before grepping (use `ast` parse instead — only checks actual `Import` nodes).
- `openai` SDK version drift may break the exception-mapping — pinned to `>=1.50,<2.0` in pyproject.

## Self-check (10 rules)

`shared/llm/` — no core/packs coupling. ✓ N/A org_id (no tables). ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. ✓ N/A permissions (invoked via Step 1's guarded router). ✓ pack.yaml untouched. ✓ ~400 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 2 — LLM client interface + OpenAI adapter (shared/llm/)
Files: 9
Verify: complete/stream/probe/embed against mocked OpenAI; base_url pinned;
        boundary pin-test blocks stray openai imports.
Tests: ~10 pytest cases.
Awaiting "proceed".
```
