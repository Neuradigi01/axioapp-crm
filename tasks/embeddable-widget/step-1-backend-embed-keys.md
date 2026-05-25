# Step 1 — Backend: `embed_keys` table + key issuance/revocation

**Goal:** Land the per-org API key model used by the public widget endpoint. Keys are issued by Owner/Admin from Settings, hashed at rest, shown to the user exactly once, and revocable. One key per org is enough for v1 (with the option to issue more later); each key has an optional friendly name and tracks last-used-at.
**Track:** Embeddable Widget
**Status:** Done — `embed_keys` table shipped via migration `0044_embed_keys` with `(org_id)` + RLS + partial-prefix index over non-revoked rows (`WHERE revoked_at IS NULL`). Sub-package `core/embed/` ships `models.py` (EmbedKey, no FK on created_by/revoked_by per post-0037), `schemas.py` (EmbedKeyIssue / Read / IssueResponse — Read NEVER exposes the secret), `service.py` (issue / revoke / list_keys / find_by_plain_key — uses **bcrypt** instead of Argon2id to match existing project convention; same security property, no new dep), `router.py` (POST issue / GET list / DELETE revoke, all gated by `settings.integrations.embed.manage`), and `module.py` (descriptor with `menu_position=None` — no sidebar entry; Owner manages from Settings → Integrations in Step 4). Permission key auto-registers via module sweep; added to `_CORE_ADMIN_KEYS` + demo seed; backfilled across all 7 existing orgs. End-to-end verified: plaintext `pk_live_<32-base62>` returned once, bcrypt hash stored (plaintext NOT in hash), lookup-by-plain resolves correctly, post-revoke lookup returns None, re-revoke is idempotent (one audit event), garbage key returns None, `last_used_at` + SHA-hashed IP updated on lookup. Migration round-trips clean. Notable adaptations: (a) bcrypt instead of Argon2id (existing convention); (b) no `core/audit/events.py` (codebase convention — action names: `embed.key.issued`, `embed.key.revoked`); (c) `last_used_ip` is `sha256(ip)[:16]` not raw IP (privacy).
**Depends on:** Phase 1.5 (permissions, audit, org settings), Manual Lead Entry Step 1 (the `lead.source` enum — `widget` value already present).

---

## Scope

In-scope:

- Alembic migration adding `embed_keys` table.
- SQLAlchemy `EmbedKey` model + Pydantic schemas (`EmbedKeyIssue`, `EmbedKeyRead`, `EmbedKeyIssueResponse`).
- `core/embed/service.py`:
  - `issue(org_id, actor, name=None) -> tuple[EmbedKey, str]` — generates `pk_live_` + 32 base62 chars, returns the **plain-text key once** alongside the persisted record (which stores only an Argon2id hash + a 6-char prefix for display).
  - `revoke(org_id, actor, key_id)` — soft-revokes by setting `revoked_at`.
  - `find_by_plain_key(plain) -> EmbedKey | None` — used by the submission endpoint (Step 2). Looks up via the prefix index then verifies the hash.
- Admin endpoints on `/api/v1/embed/keys`:
  - `POST /` — issue. Returns `{id, name, prefix, secret: "pk_live_…", created_at}`. Secret only appears in this response, never again.
  - `GET /` — list (no secret).
  - `DELETE /{id}` — revoke.
- New permission key `settings.integrations.embed.manage`. Default-granted to Owner + Admin.
- Audit events: `embed.key.issued`, `embed.key.revoked`.
- Tests: hash never returned, revoked keys ignored on lookup, RLS isolation, permission gate.

Out of scope:

- No public submission endpoint — Step 2.
- No widget config — Step 3.
- No frontend — Step 4.
- No "rotate" endpoint (revoke + reissue is a two-call flow for v1).

## The `embed_keys` table

```sql
CREATE TABLE embed_keys (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id),
    name        TEXT,                              -- e.g. "Main site form", nullable
    prefix      CHAR(11) NOT NULL,                 -- 'pk_live_AbC' — first 11 chars of the plain key, indexed for fast lookup
    hash        TEXT NOT NULL,                     -- Argon2id hash of the full plain key
    created_by  UUID NOT NULL REFERENCES users(id),
    last_used_at TIMESTAMPTZ,
    last_used_ip TEXT,                             -- last-octet hashed (privacy-respecting)
    revoked_at  TIMESTAMPTZ,
    revoked_by  UUID REFERENCES users(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX embed_keys_prefix_idx ON embed_keys (prefix) WHERE revoked_at IS NULL;
CREATE INDEX embed_keys_org_idx ON embed_keys (org_id, created_at DESC);

ALTER TABLE embed_keys ENABLE ROW LEVEL SECURITY;
CREATE POLICY embed_keys_tenant_isolation ON embed_keys
    USING (org_id = current_setting('app.org_id', true)::uuid);
```

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/0XXX_add_embed_keys.py` | created |
| `api/src/app/core/embed/__init__.py` | created |
| `api/src/app/core/embed/models.py` | created |
| `api/src/app/core/embed/schemas.py` | created |
| `api/src/app/core/embed/service.py` | created |
| `api/src/app/core/embed/router.py` | created |
| `api/src/app/core/permissions/registry.py` | modified — register `settings.integrations.embed.manage` |
| `api/src/app/core/audit/events.py` | modified (small) — declare `EMBED_KEY_ISSUED`, `EMBED_KEY_REVOKED` |
| `api/src/app/main.py` | modified (small) — include the new router |
| `api/tests/test_embed_keys.py` | created |

**10 files, 1 migration.** At rule-8 ceiling; new sub-package is one logical unit.

## Plan

1. Create migration + run upgrade/downgrade locally.
2. Build the model + schemas. `EmbedKeyRead` includes `prefix` (for "your key starts with `pk_live_AbC…`") but never the secret.
3. Implement `service.issue()`:
   - Generate a 32-char base62 random string (`secrets.choice` from `string.ascii_letters + string.digits`).
   - Build `plain = f"pk_live_{random}"` → length 40.
   - Compute `prefix = plain[:11]` (`"pk_live_AbC"`).
   - Compute `hash = argon2.PasswordHasher().hash(plain)`.
   - Persist row. Return (row, plain).
   - Emit `embed.key.issued` audit event.
4. Implement `service.revoke()`:
   - Set `revoked_at = now()`, `revoked_by = actor`. RLS already enforces org boundary.
   - Emit `embed.key.revoked` audit event.
5. Implement `service.find_by_plain_key()`:
   - Extract prefix from the plain key (first 11 chars).
   - Look up non-revoked keys with matching prefix.
   - For each candidate, verify with Argon2; first match wins (prefix collisions ≈ 1 in 56B).
   - On match, update `last_used_at` + `last_used_ip` (best-effort, fire-and-forget — must not slow the submission path; defer to a background task if needed).
6. Build the router. Owner-only endpoints; permission gate.
7. Tests.

## Tests

`api/tests/test_embed_keys.py`:

- **Issue returns secret once:** POST → response has `secret: "pk_live_…"`. List endpoint then returns only prefix.
- **Hash storage:** the persisted row's `hash` does not contain the plain key as substring.
- **Lookup by plain key:** `service.find_by_plain_key(plain)` returns the row. With a random plain key, returns `None`.
- **Revoked keys not found:** revoke, then lookup → `None`.
- **Revoke is idempotent:** revoke twice → second call is a no-op (no error, no double audit event).
- **RLS:** Org A creates a key. Org B's list does not see it.
- **Permission gate:** Employee POST → 403.
- **Audit events:** issue emits `embed.key.issued`; revoke emits `embed.key.revoked`.

## Smoke

```powershell
docker exec template_api-api-1 uv run alembic upgrade head
docker exec template_api-api-1 uv run pytest tests/test_embed_keys.py -v

# Issue a key as Owner
$token = "<owner JWT>"
$r = curl -X POST http://localhost:8000/api/v1/embed/keys `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -d '{"name":"smoke key"}'
$secret = ($r | ConvertFrom-Json).secret
$secret  # pk_live_…

# List doesn't include secret
curl http://localhost:8000/api/v1/embed/keys -H "Authorization: Bearer $token"
# Expect: [{id, name:"smoke key", prefix:"pk_live_…", created_at, last_used_at:null, revoked_at:null}]
```

## Risks

- **Argon2id verification cost on every submission:** Argon2 is intentionally slow (~50–100ms). On the submission hot path, this is acceptable for v1 (rate limit caps abuse), but eventually we'd cache `prefix → row` in Redis with a short TTL and only re-verify on cache miss. Out of scope here; flag as a follow-on if submission latency becomes a concern.
- **Prefix-collision attacks:** an attacker who learns a prefix could brute-force suffixes. Mitigations: 32 random base62 chars (~190 bits entropy in suffix), Argon2id slow verification, per-IP rate limit in Step 2. Acceptable risk for v1.
- **`last_used_ip` PII concern:** store last-octet hashed (`hashlib.sha256(ip).hexdigest()[:16]`) so the abuse-investigation surface in Step 9 can group by IP without storing PII. Document in the model.

## Rollback

`alembic downgrade -1` removes the table. Delete the new files. Revert permissions edit. The widget bundle (later steps) cannot authenticate without this; rollback unlands the whole track effectively.
