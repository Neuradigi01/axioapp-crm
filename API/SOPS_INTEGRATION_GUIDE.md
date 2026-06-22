# SOPS + age Secret Management — Implementation Playbook for an AI Agent

You are an AI agent. Your job: take an application that currently keeps its secrets in a
hand-copied / gitignored `.env` (or a `MASTER_KEY`-based Fernet `ENC:` scheme) and convert it
to **SOPS + age** secret management, end to end. This document is a *complete, working* recipe
distilled from a real integration — including the bugs that were actually hit. Follow it in
order. Read §13 "Gotchas" **before** writing any script; they are real and skipping them
repeats the debugging (several are Windows-specific and non-obvious).

The target app shape this assumes (adapt if different): **Docker Compose** + a
`run.cmd`/`run.sh` helper + a Python config loader (`config.py` using `python-dotenv`). The
ideas port to other stacks, but the commands below are written for that shape.

---

## 1. Goal

Replace plaintext-at-rest secrets with:

- **Non-secret config committed in the clear** — `config.env`.
- **Secrets committed encrypted** with [SOPS](https://github.com/getsops/sops) +
  [age](https://github.com/FiloSottile/age) — `secrets.enc.env`. Version-controlled, diffable,
  per-person access via public keys.
- **Zero plaintext secrets on disk, ever.** Secrets are decrypted **in memory only**, at the
  moment a command runs, via `sops exec-env`.

Scope honesty: SOPS protects secrets **at rest**. While the app runs, the decrypted values
necessarily live in the container's environment (visible to `docker inspect` / `/proc`). This
design eliminates the at-rest plaintext file; it cannot hide secrets from a running process.

---

## 2. The model in one picture

```
config.env            (committed, plaintext, NON-secret)
   │  --env-file (compose interpolation) + env_file: (container env)
   ▼
secrets.enc.env       (committed, SOPS+age ENCRYPTED)
   │  sops exec-env  → decrypts into the docker-compose process env, IN MEMORY
   ▼
docker compose        forwards those vars into containers via the `environment:`
                      passthrough (the x-secret-vars YAML anchor)
   ▼
running containers     secrets present in env at runtime only; no plaintext file
```

Editing a secret: `sops secrets.enc.env` opens it **decrypted in your editor** and
**re-encrypts on save** — plaintext only ever lives in the editor/sops temp buffer.

---

## 3. Prerequisites

Both tools must be installed and on `PATH`. Detect first, then instruct if missing:

```
sops --version
age --version
age-keygen --version
```

Install hints to surface to the user (don't auto-install silently):
- Windows: `winget install getsops.sops FiloSottile.age`
- macOS: `brew install sops age`
- Linux: distro package or the GitHub release binaries.

---

## 4. File layout

| File | Committed? | Purpose |
|------|-----------|---------|
| `config.env` | ✅ | Non-secret config (ports, hosts, flags, **public** keys) |
| `secrets.enc.env` | ✅ | Secrets, SOPS+age encrypted. **Note the name** (§5.1) |
| `.sops.yaml` | ✅ | Encryption rule + recipient **public** keys |
| `run.cmd` / `run.sh` | ✅ | Helper (Windows/dev and Linux-Mac/prod). Full templates in Appendix A/B |
| `config.py` (or your loader) | ✅ | Loads `config.env`; reads secrets from env (injected at runtime) |
| `docker-compose*.yml` | ✅ | `env_file: [config.env]` + `environment:` secret passthrough |
| `.gitignore` / `.dockerignore` / `.gitattributes` | ✅ | See §11 |
| age **private** key | ❌ never | Per machine, at `~/.config/sops/age/keys.txt` |

**There is no plaintext secrets file in the repo or on disk.**

---

## 5. Key design decisions (the "why" — do not change blindly)

### 5.1 The encrypted file is named `secrets.enc.env` (NOT `.env.secrets.enc`)
`sops exec-env` has **no `--input-type` flag** — it must auto-detect format, and SOPS detects
"dotenv" only when the filename **ends in `.env`**. `secrets.enc.env` ends in `.env` → detected
as dotenv → `exec-env`, `sops <file>` (edit), and `updatekeys` all work with no type flag. A
name ending in `.enc` → SOPS guesses binary/JSON → everything breaks.

### 5.2 `sops exec-env`, not a decrypted file + `env_file:`
`exec-env` decrypts into the spawned process's environment **in memory** and never writes
plaintext to disk — the core security goal. Decrypting to a file and pointing `env_file:` at it
would leave plaintext at rest, which is exactly what we're avoiding.

### 5.3 The `environment:` passthrough + `x-secret-vars` anchor
`exec-env` puts secrets in the **compose process** environment. Docker does not auto-forward
host env into containers — each variable must be declared. List them once as a YAML anchor with
null values (= "pass through from the process env") and merge it into every service.

### 5.4 Both `--env-file config.env` AND `env_file: [config.env]`
Two different scopes:
- **`--env-file config.env`** (CLI flag) fills the **interpolation** context for `${VAR}`
  *inside the compose YAML* (ports, `command:` strings). Docker only auto-loads a file literally
  named `.env`; ours is `config.env`, so pass it explicitly.
- **`env_file: [config.env]`** (per service) injects the non-secret config into the **container**.
Secrets need neither — they arrive via `exec-env` + the `environment:` passthrough.

### 5.5 `SOPS_AGE_KEY_FILE` set explicitly
SOPS's default age-key search path is OS-specific (`~/.config/...` Linux,
`~/Library/Application Support/...` macOS, `%AppData%\sops\age\...` Windows). The helper writes
the key to one path and points SOPS at it via `SOPS_AGE_KEY_FILE` to avoid "failed to load age
identities".

### 5.6 Invoke real binaries inside `exec-env`, never a nested `cmd /c`
On Windows, `sops exec-env FILE "<command>"` runs `<command>` through `cmd /C "..."`. If
`<command>` itself starts another `cmd /c ...`, you get a stray trailing `"` injected into the
inner command line (a real bug — see G8). So inside the quoted command, call `docker compose
...` (a real executable) **directly**. Don't wrap it in `cmd /c`.

---

## 6. Step-by-step implementation (in order)

### 6.1 Inventory and categorize the existing secrets
Read the current `.env` (have the user decrypt it first if it uses `ENC:`/`MASTER_KEY`). Sort
every key into three buckets:

- **A — code defaults** (timeouts, TTLs, formats, enums whose value equals the loader's
  default): leave as `os.getenv("X", "default")` in the loader; put in **no file**.
- **B — non-secret config → `config.env`**: DB host/port/name/user, Redis host/port, URLs,
  ports, feature flags, and **public** keys (reCAPTCHA *site* key, Stripe *publishable* key,
  Firebase **web** config, Sentry DSN).
- **C — secrets → `secrets.enc.env`**: passwords, private keys, API keys, signing keys, webhook
  secrets, OAuth client *secrets*, the app's data-encryption key (e.g. `FERNET_KEY`).

Litmus test: *"Harmful if it leaked in a public repo?"* Yes → bucket C.

Environment-specific NON-secret values (e.g. `IS_DEVELOPMENT`, `SENTRY_ENV`) are bucket B but
**must not** go in `config.env` (which is shared by dev and prod) — they go in the per-env
compose overlay (§6.7).

> ⚠️ Preserve the app's data-encryption key (e.g. `FERNET_KEY`) **verbatim**. Rotating it makes
> any data already encrypted with it (stored 2FA secrets, tokens) undecryptable. Migrate it; do
> not regenerate it. You may safely regenerate a `JWT_SECRET_KEY` (only invalidates sessions)
> and **should** generate a strong value for any newly-required password (e.g. Redis, §6.7).

### 6.2 Generate the age keypair (per machine; never overwrite an existing key)
```
# Windows (PowerShell)
$dir="$env:USERPROFILE\.config\sops\age"; New-Item -ItemType Directory -Force $dir | Out-Null
if (-not (Test-Path "$dir\keys.txt")) { age-keygen -o "$dir\keys.txt" }
age-keygen -y "$dir\keys.txt"          # prints the age1... PUBLIC key

# Linux / Mac
mkdir -p ~/.config/sops/age
[ -f ~/.config/sops/age/keys.txt ] || age-keygen -o ~/.config/sops/age/keys.txt
age-keygen -y ~/.config/sops/age/keys.txt
```
The private key never leaves the machine and is never committed. Only the `age1...` public key
is shared.

### 6.3 Create `.sops.yaml`
```yaml
creation_rules:
  # secrets.enc.env ends in .env so SOPS auto-detects dotenv (exec-env has no --input-type).
  # age: is a comma-separated list of recipient PUBLIC keys.
  - path_regex: secrets\.enc\.env$
    age: >-
      age1PUBLICKEYONE,
      age1PUBLICKEYTWO
```

### 6.4 Create `config.env` (committed, non-secret)
Put bucket-B keys that are the **same across environments**. Header comment stating the split.
No inline trailing comments after a value (some parsers fold them into the value) — comments on
their own line. Example shape:
```
# Non-secret config — committed in plaintext. Secrets live in secrets.enc.env (SOPS).
# Env-specific values (IS_DEVELOPMENT, ...) live in the compose overlays, not here.
COMPOSE_PROJECT_NAME=myapp
DB_HOST=...
DB_PORT=...
REDIS_HOST=redis
# ...public keys, ports, flags...
```

### 6.5 Create the encrypted `secrets.enc.env`
You cannot use an interactive editor non-interactively, so write plaintext then encrypt
**in place** (the in-place encrypt overwrites the file with ciphertext — no separate plaintext
remains):
```
# write secrets.enc.env in plaintext (KEY=value lines, bucket C), then:
sops --encrypt --in-place secrets.enc.env      # run from the dir containing .sops.yaml
```
For a multi-line value like a PEM private key, keep it on ONE line with literal `\n` separators,
exactly as the source `.env` had it (the app converts with `.replace("\\n","\n")` — see G7).
Verify it encrypted (readable keys, `ENC[...]` values):
```
sops -d secrets.enc.env | head        # should print the real plaintext back
```

### 6.6 Rewrite the config loader (`config.py`)
Remove any prior scheme (Fernet `_env()`/`ENC:` prefix, `MASTER_KEY`, a `manage_secrets.py`
CLI). Load **only** `config.env`; read everything (config and secrets) via `os.getenv`:
```python
import os
from pathlib import Path
from dotenv import load_dotenv

# Non-secret config from config.env. Secrets are injected at runtime by `sops exec-env`
# (see run.cmd / run.sh) and read via os.getenv — no plaintext secrets file on disk.
_BASE_DIR = Path(__file__).resolve().parent
load_dotenv(_BASE_DIR / "config.env")

DB_PASSWORD = os.getenv("DB_PASSWORD")        # injected at runtime
# ...etc...
```
Grep the codebase and delete every reference to the old scheme (`MASTER_KEY`, `ENC:`, `_env(`,
`manage_secrets`). Then delete `manage_secrets.py` itself.

### 6.7 Wire Docker Compose
**Base `docker-compose.yml`** — declare the secret passthrough once and merge it everywhere, and
put shared infra (Redis) here so it runs in every environment:
```yaml
# Null value = "pass through from the compose process env", which run.* populate via exec-env.
x-secret-vars: &secret-vars
  DB_PASSWORD:
  JWT_SECRET_KEY:
  FERNET_KEY:
  REDIS_PASSWORD:
  # ...every secret key name from secrets.enc.env...

services:
  api:
    build: .
    env_file:
      - config.env            # non-secrets into the container
    environment:
      <<: *secret-vars        # secrets, passed through from the exec-env process
    depends_on:
      - redis
  # celery / celery-beat / flower: same env_file + environment: { <<: *secret-vars }, under a
  # `profiles: [celery]` if optional.

  redis:
    image: "redis:7-alpine"
    restart: unless-stopped
    command: redis-server --requirepass ${REDIS_PASSWORD}   # secret, resolved via exec-env
    volumes:
      - redis_data:/data

volumes:
  redis_data:
```
Notes:
- Generate a **strong, non-empty** `REDIS_PASSWORD` (bucket C). If the app builds its Redis URL
  conditionally (auth only when the password is set), enabling a password is transparent.
- Don't publish a Redis host port — services reach it as `redis:6379` on the internal network,
  so multiple stacks on one host never collide.

**Per-environment overlays** — only env-specific NON-secret values, as an anchor merged into
every service (compose merges `environment` maps across files):
```yaml
# docker-compose.dev.yml
x-dev-env: &dev-env
  IS_DEVELOPMENT: "true"
services:
  api:    { environment: { <<: *dev-env } }
  celery: { environment: { <<: *dev-env } }
  # ...beat, flower...

# docker-compose.prod.yml — same shape with IS_DEVELOPMENT: "false"
```
Remove any old `env_file: .env`, `MASTER_KEY`, `/etc/master.env`, and any now-unused
`ENV=...` var (grep first; if nothing reads `ENV`, drop it).

### 6.8 Write `run.cmd` and `run.sh`
Use the complete, tested templates in **Appendix A** (`run.cmd`) and **Appendix B** (`run.sh`).
They provide: grouped + colored help with `-h`/`--help`/`help` aliases; `up`/`down`/`restart`
on the full stack; `shell [service]`; `migrate`/`upgrade`/`downgrade`/`seed`;
`lock`/`lock-upgrade`; and `secrets-keygen`/`secrets-edit`/`secrets-rekey`. Adapt the variable
block at the top (compose files, secret file name, uv image, project specifics).

Critical: `run.cmd` must be **CRLF + ASCII**; `run.sh` must be **LF + ASCII** (G1, G9).

### 6.9 Ignore / attributes — §11.

### 6.10 Delete the old scheme
`.env`, `.env.example`, `manage_secrets.py`, any old `docker-helper.*`, and any standalone
compose file that referenced `.env` (e.g. a separate `docker-compose.redis.yml`) if Redis now
lives in the base compose. Confirm nothing references the deleted files (grep the repo + README).

---

## 7. Verification checklist (run these; they catch the real failures)

1. **Help parses cleanly (G1).** `cmd /c ".\run.cmd help"` prints the grouped help with no
   "not recognized" / parse errors / Docker side effects. `bash -n run.sh` passes.
   - **Test `.cmd` via `cmd.exe`, not PowerShell** (G10): PowerShell 5.1 mangles quoted native
     args and will mislead you with stray quotes that don't happen under `cmd.exe`.
2. **Line endings.** `file run.sh` says "shell script ... executable" **without** "with CRLF
   line terminators". `run.cmd` is "DOS batch ... with CRLF". (PowerShell byte check is the
   tiebreaker: count bytes equal to 13.)
3. **Only `config.env` + `secrets.enc.env` exist; no plaintext secrets file** (G6). Grep the
   tree for a known secret value — it must appear **only** inside `secrets.enc.env`.
4. **Encryption shape.** `secrets.enc.env` shows **readable keys** with `ENC[...]` **values**
   (proves dotenv auto-detect, G2). `sops -d secrets.enc.env` returns the plaintext.
5. **Rekey works.** `sops updatekeys -y secrets.enc.env` succeeds and re-wraps to all recipients
   in `.sops.yaml` (proves G3 + G4 + G5-naming).
6. **THE killer test — passthrough without starting containers.** Render the merged compose
   config *through* exec-env and confirm every secret resolved into the service environment:
   ```
   # run inside cmd.exe on Windows (a .cmd line), or any shell on Linux/Mac:
   sops exec-env secrets.enc.env "docker compose --env-file config.env -f docker-compose.yml -f docker-compose.dev.yml config"
   ```
   In the rendered `api` service `environment:` you should see `DB_PASSWORD`, `REDIS_PASSWORD`,
   etc. with their real values, and the Redis `command:` `--requirepass <real value>`. Empty/
   missing values mean the exec-env or passthrough chain is broken (G5/G8). This proves the
   whole chain in seconds and needs no DB/containers.
7. **git status:** `config.env` / `secrets.enc.env` / `.sops.yaml` / `run.*` / `.gitattributes`
   tracked; **no plaintext secrets tracked**, age private key not tracked.

---

## 8. Day-to-day workflow

- **Run:** `run.cmd up` / `./run.sh up` — full stack; secrets decrypted in-memory for that
  command. `restart` = down+up. `shell [service]` opens a shell in a running container.
- **Change a secret:** `run.cmd secrets-edit` → edit in your editor → save (auto re-encrypts) →
  commit `secrets.enc.env`.
- **Onboard a teammate:** they run `secrets-keygen` and send their `age1...` public key; you add
  it to `.sops.yaml`, run `secrets-rekey`, commit `secrets.enc.env`.

---

## 9. Revocation (when someone leaves) — important

Removing a public key from `.sops.yaml` + `secrets-rekey` is **NOT** sufficient. A departed
developer may already hold the plaintext, the SOPS data key, and git history (every past
`secrets.enc.env` stays decryptable with their private key forever). True revocation = **rotate
the actual secret values at their source** (new DB password, new signing/API keys), set the new
values via `secrets-edit`, remove their key from `.sops.yaml`, `secrets-rekey`, and restart
services. Order matters: remove their key **before** re-encrypting so the new data key is never
wrapped to them. SOPS protects the file from those who never had access; it cannot un-leak what
someone already read.

---

## 10. Day-2: secrets you newly require

If the integration introduces a secret the app didn't have (e.g. a Redis password where there
was none), generate a strong value, add it to bucket C / `secrets.enc.env`, add the key name to
the `x-secret-vars` anchor, and make sure the app reads it. Verify with the §7 item-6 killer test.

---

## 11. Ignore / attributes

- **`.gitattributes`** (pin line endings — G1/G9):
  ```
  * text=auto
  *.cmd text eol=crlf
  *.bat text eol=crlf
  *.ps1 text eol=crlf
  *.sh   text eol=lf
  *.env  text eol=lf
  .env.* text eol=lf
  ```
- **`.gitignore`** — ignore age private keys (`*.agekey`, `age-key*.txt`, `keys.txt`) and,
  defensively, any manually decrypted dump (`secrets.dec.env`, `*.dec.env`). Keep ignoring a
  bare `.env` (it never matches `config.env` / `secrets.enc.env`). Do **not** ignore
  `config.env` or `secrets.enc.env` — both are committed.
- **`.dockerignore`** — exclude `secrets.enc.env`, `.sops.yaml`, age keys, `*.dec.env`, and the
  `run.*` helpers from the image (secrets are injected at runtime, not baked in). `config.env`
  may stay (non-secret) so the loader's `load_dotenv` works for non-Docker local runs.

---

## 12. Help UX (what "good" looks like)

The helper's `help` (and `-h` / `--help`) should print a **titled, grouped, colored** menu:
a cyan title line + dim usage line, then sections **Stack / Database / Dependencies / Secrets**,
commands in green, and the alias note on the `help` line. Colors via ANSI; in `run.sh` emit them
only when stdout is a TTY (`[ -t 1 ]`) and `NO_COLOR` is unset; in `run.cmd` capture an ESC char
via the `prompt $E` trick (Windows 10+ terminals render it, older consoles ignore it). The full
implementations are in the appendices — reproduce that structure.

---

## 13. Gotchas (real bugs hit — avoid them)

- **G1 — `.cmd` MUST be CRLF + ASCII.** `cmd.exe` mis-parses LF batch files (labels/`goto` land
  at wrong offsets; in the original build this silently ran `down -v`). Keep it ASCII too
  (em-dash / box chars mojibake under cmd's code page). Enforce via `.gitattributes` and write
  the file CRLF/ASCII.
- **G2 — encrypted file name ends in `.env`.** `secrets.enc.env`, not `.env.secrets.enc`. SOPS
  must auto-detect dotenv from the `.env` suffix (no `--input-type` on `exec-env`). Wrong suffix
  → `exec-env`/`edit`/`updatekeys` all break.
- **G3 — `SOPS_AGE_KEY_FILE`.** SOPS's default key path is OS-specific (not `~/.config` on
  Windows). Export `SOPS_AGE_KEY_FILE` from the helper pointing at the path `secrets-keygen`
  writes to, or you get "failed to load age identities".
- **G4 — `.sops.yaml` `path_regex` must match the filename.** Use `secrets\.enc\.env$`. A
  non-matching regex → "no matching creation rules found" on encrypt/`updatekeys`.
- **G5 — passthrough needs the process env populated.** The null-value `environment:` entries
  resolve only because `sops exec-env` set them in the compose process. Running `docker compose`
  *without* the `exec-env` wrapper gives containers empty secrets. Every secret-needing command
  must go through the wrapper.
- **G6 — don't hand-edit `secrets.enc.env`.** It has an integrity MAC and per-recipient wrapped
  keys; editing any line corrupts it. Change secrets only via `secrets-edit`.
- **G7 — multi-line keys (PEM) use literal `\n`.** Store the value on one line with `\n`
  separators, as the source `.env` had it. App code typically does
  `KEY.replace("\\n", "\n")`, which is robust whether `exec-env` yields literal `\n` or real
  newlines — so it just works. Don't reformat it into a YAML block.
- **G8 — inside `exec-env`, call binaries directly; no nested `cmd /c`.** On Windows
  `sops exec-env FILE "<cmd>"` runs `<cmd>` via `cmd /C "..."`. A `cmd /c ...` *inside* `<cmd>`
  gets a stray trailing `"` injected and breaks. Put `docker compose ...` directly in the quoted
  string. Likewise prefer `docker compose run --rm api alembic upgrade head` over
  `--entrypoint "alembic upgrade head"` to avoid nested quotes entirely (works when the image
  has no `ENTRYPOINT`, only `CMD`). For `migrate`, keep the message a single token (snake_case)
  to dodge quoting; alembic messages are snake_case by convention anyway.
- **G9 — `run.sh` MUST be LF.** A CRLF `run.sh` fails on Linux/Mac with
  `/bin/bash^M: bad interpreter`. Windows editors/tools may silently rewrite it to CRLF on
  save — re-verify with `file run.sh` after every write (it must NOT say "with CRLF line
  terminators").
- **G10 — test `.cmd` under `cmd.exe`, not PowerShell.** PowerShell 5.1's native-arg quoting
  injects stray quotes that make a *correct* `.cmd` look broken (and can hide real breakage).
  Validate with `cmd /c ".\run.cmd <args>"`.
- **G11 — never commit a plaintext secrets file.** Confirm none is produced; only `config.env`
  (non-secret) and `secrets.enc.env` (encrypted) are tracked. Also check git **history** for a
  previously-committed `.env`; if real secrets were ever committed, they must be rotated (history
  rewrite alone is not enough, and is the user's call).

---

## Appendix A — `run.cmd` (Windows / dev; CRLF + ASCII)

> Adapt the variable block (`COMPOSE_FILES`, `SECRETS_FILE`, `PROFILE_FLAGS`, `UV_IMAGE`) and the
> command set to the target app. Help is grouped/colored with `-h`/`--help` aliases; `up`/`down`
> run the full stack; `shell [service]` opens a shell; DB commands use `run --rm api <cmd>`
> (no nested quotes). Write this file as CRLF/ASCII.

```bat
@echo off
REM Manage the API application stack (Windows / development compose files).
REM Secrets are decrypted in-memory by `sops exec-env` for each stack/DB command and
REM forwarded into containers via the `environment:` passthrough - never written to disk.
REM Run `run.cmd help` for the command list.

setlocal enabledelayedexpansion
set ENV_FILE_FLAGS=--env-file config.env
set COMPOSE_FILES=-f docker-compose.yml -f docker-compose.dev.yml
set PROFILE_FLAGS=--profile celery
set UV_IMAGE=ghcr.io/astral-sh/uv:0.5-python3.13-bookworm-slim
set SECRETS_FILE=secrets.enc.env
set AGE_KEY_DIR=%USERPROFILE%\.config\sops\age
set AGE_KEY_FILE=%AGE_KEY_DIR%\keys.txt
set SOPS_AGE_KEY_FILE=%AGE_KEY_FILE%

REM Capture an ESC char (0x1B) for ANSI colors via the prompt trick.
for /f %%a in ('echo prompt $E ^| cmd') do set "ESC=%%a"
set "C_TITLE=%ESC%[1;36m"
set "C_SECTION=%ESC%[1;33m"
set "C_CMD=%ESC%[32m"
set "C_DIM=%ESC%[2m"
set "C_ERR=%ESC%[31m"
set "C_RESET=%ESC%[0m"

if "%1"=="" ( call :print_help & exit /b 0 )

if /i "%1"=="help" ( call :print_help & exit /b 0
) else if /i "%1"=="-h" ( call :print_help & exit /b 0
) else if /i "%1"=="--help" ( call :print_help & exit /b 0
) else if /i "%1"=="up" ( call :do_up & exit /b !errorlevel!
) else if /i "%1"=="down" ( call :do_down & exit /b !errorlevel!
) else if /i "%1"=="restart" (
    echo Restarting the API stack...
    call :do_down
    if errorlevel 1 exit /b 1
    call :do_up
    exit /b !errorlevel!
) else if /i "%1"=="shell" (
    call :require_secrets
    if errorlevel 1 exit /b 1
    set "service=%~2"
    if "!service!"=="" set "service=api"
    echo Opening a shell in service '!service!'...
    sops exec-env %SECRETS_FILE% "docker compose %ENV_FILE_FLAGS% %COMPOSE_FILES% %PROFILE_FLAGS% exec !service! bash"
    exit /b !errorlevel!
) else if /i "%1"=="lock" (
    echo Regenerating uv.lock from pyproject.toml...
    docker run --rm -v "%cd%":/app -w /app %UV_IMAGE% uv lock
    exit /b !errorlevel!
) else if /i "%1"=="lock-upgrade" (
    echo Regenerating uv.lock with upgrades...
    docker run --rm -v "%cd%":/app -w /app %UV_IMAGE% uv lock --upgrade
    exit /b !errorlevel!
) else if /i "%1"=="migrate" (
    call :require_secrets
    if errorlevel 1 exit /b 1
    set "msg=%~2"
    if "!msg!"=="" set "msg=auto_migration"
    echo Generating Alembic migration: !msg!
    sops exec-env %SECRETS_FILE% "docker compose %ENV_FILE_FLAGS% %COMPOSE_FILES% run --rm api alembic revision --autogenerate -m \"!msg!\""
    exit /b !errorlevel!
) else if /i "%1"=="upgrade" (
    call :require_secrets
    if errorlevel 1 exit /b 1
    set "steps=%~2"
    if "!steps!"=="" (
        sops exec-env %SECRETS_FILE% "docker compose %ENV_FILE_FLAGS% %COMPOSE_FILES% run --rm api alembic upgrade head"
    ) else (
        sops exec-env %SECRETS_FILE% "docker compose %ENV_FILE_FLAGS% %COMPOSE_FILES% run --rm api alembic upgrade +!steps!"
    )
    exit /b !errorlevel!
) else if /i "%1"=="downgrade" (
    call :require_secrets
    if errorlevel 1 exit /b 1
    set "steps=%~2"
    if "!steps!"=="" set "steps=1"
    sops exec-env %SECRETS_FILE% "docker compose %ENV_FILE_FLAGS% %COMPOSE_FILES% run --rm api alembic downgrade -!steps!"
    exit /b !errorlevel!
) else if /i "%1"=="seed" (
    call :require_secrets
    if errorlevel 1 exit /b 1
    set "seedtype=%~2"
    if "!seedtype!"=="" (
        sops exec-env %SECRETS_FILE% "docker compose %ENV_FILE_FLAGS% %COMPOSE_FILES% run --rm api python -m src.seeds.run"
    ) else (
        sops exec-env %SECRETS_FILE% "docker compose %ENV_FILE_FLAGS% %COMPOSE_FILES% run --rm api python -m src.seeds.run !seedtype!"
    )
    exit /b !errorlevel!
) else if /i "%1"=="secrets-keygen" (
    where age-keygen >nul 2>nul
    if errorlevel 1 ( echo Error: age not installed ^(winget install FiloSottile.age^). & exit /b 1 )
    if exist "%AGE_KEY_FILE%" (
        echo An age key already exists at %AGE_KEY_FILE% - not overwriting.
    ) else (
        if not exist "%AGE_KEY_DIR%" mkdir "%AGE_KEY_DIR%"
        age-keygen -o "%AGE_KEY_FILE%"
        if errorlevel 1 exit /b 1
        echo Key generated at %AGE_KEY_FILE%. Keep the PRIVATE key secret.
    )
    echo.
    echo Your PUBLIC key - send it to whoever manages .sops.yaml:
    age-keygen -y "%AGE_KEY_FILE%"
    exit /b 0
) else if /i "%1"=="secrets-edit" (
    call :require_secrets
    if errorlevel 1 exit /b 1
    where code >nul 2>nul
    if not errorlevel 1 set "EDITOR=code --wait"
    sops %SECRETS_FILE%
    exit /b !errorlevel!
) else if /i "%1"=="secrets-rekey" (
    where sops >nul 2>nul
    if errorlevel 1 ( echo Error: sops not installed. & exit /b 1 )
    if not exist "%SECRETS_FILE%" ( echo Error: %SECRETS_FILE% not found. & exit /b 1 )
    echo Re-encrypting %SECRETS_FILE% to the recipients in .sops.yaml ...
    sops updatekeys -y %SECRETS_FILE%
    exit /b !errorlevel!
) else (
    echo %C_ERR%Error: Invalid command '%1'.%C_RESET%
    echo.
    call :print_help
    exit /b 1
)

REM Guard against fall-through into the internal labels below.
exit /b 0

:print_help
echo %C_TITLE%MyApp stack runner ^(development / Windows^)%C_RESET%
echo %C_DIM%Usage: run.cmd ^<command^> [args]%C_RESET%
echo.
echo %C_SECTION%Stack%C_RESET%
echo   %C_CMD%up%C_RESET%                 Start the full stack ^(api + redis + celery + beat + flower^)
echo   %C_CMD%down%C_RESET%               Stop and remove the stack ^(with volumes^)
echo   %C_CMD%restart%C_RESET%            Down then up ^(clean reload of code/config^)
echo   %C_CMD%shell [service]%C_RESET%    Open a shell in a running service ^(default: api^)
echo.
echo %C_SECTION%Database%C_RESET%
echo   %C_CMD%migrate [msg]%C_RESET%      Generate an Alembic migration from model changes
echo   %C_CMD%upgrade [N]%C_RESET%        Apply migrations ^(default: all pending^)
echo   %C_CMD%downgrade [N]%C_RESET%      Revert migrations ^(default: 1 step back^)
echo   %C_CMD%seed [type]%C_RESET%        Run seeds ^(all^|admin^|routes^|countries^)
echo.
echo %C_SECTION%Dependencies%C_RESET%
echo   %C_CMD%lock%C_RESET%               Regenerate uv.lock from pyproject.toml
echo   %C_CMD%lock-upgrade%C_RESET%       Regenerate uv.lock with upgrades
echo.
echo %C_SECTION%Secrets ^(SOPS + age^)%C_RESET%
echo   %C_CMD%secrets-keygen%C_RESET%     Generate this machine's age key; print the public key
echo   %C_CMD%secrets-edit%C_RESET%       Edit secrets.enc.env ^(decrypts in your editor^)
echo   %C_CMD%secrets-rekey%C_RESET%      Re-encrypt secrets.enc.env to current .sops.yaml recipients
echo.
echo   %C_CMD%help%C_RESET%               Show this help ^(aliases: -h, --help^)
goto :eof

:require_secrets
where sops >nul 2>nul
if errorlevel 1 ( echo Error: sops not installed ^(install sops + age^). & exit /b 1 )
if not exist "%SECRETS_FILE%" ( echo Error: %SECRETS_FILE% not found. Run "run.cmd secrets-keygen" and get added to .sops.yaml. & exit /b 1 )
exit /b 0

:do_up
call :require_secrets
if errorlevel 1 exit /b 1
echo Starting the full API stack...
sops exec-env %SECRETS_FILE% "docker compose %ENV_FILE_FLAGS% %COMPOSE_FILES% %PROFILE_FLAGS% up --build -d"
exit /b !errorlevel!

:do_down
call :require_secrets
if errorlevel 1 exit /b 1
echo Stopping and removing the full API stack...
sops exec-env %SECRETS_FILE% "docker compose %ENV_FILE_FLAGS% %COMPOSE_FILES% %PROFILE_FLAGS% down -v"
exit /b !errorlevel!
```

---

## Appendix B — `run.sh` (Linux / Mac / prod; LF + ASCII)

> Same command set as Appendix A, prod compose files, with bash niceties (TTY-gated colors,
> `dc()` helper). Write this file with **LF** line endings; verify with `file run.sh`.

```bash
#!/bin/bash
# Manage the API application stack (Linux / Mac, production compose files).
# Secrets are decrypted in-memory by `sops exec-env` per command - never written to disk.
# Run `./run.sh help` for the command list.

set -e

ENV_FILE_FLAGS="--env-file config.env"
COMPOSE_FILES="-f docker-compose.yml -f docker-compose.prod.yml"
PROFILE_FLAGS="--profile celery"
UV_IMAGE="ghcr.io/astral-sh/uv:0.5-python3.13-bookworm-slim"
SECRETS_FILE="secrets.enc.env"
AGE_KEY_DIR="$HOME/.config/sops/age"
AGE_KEY_FILE="$AGE_KEY_DIR/keys.txt"
export SOPS_AGE_KEY_FILE="$AGE_KEY_FILE"

if [ -t 1 ] && [ -z "$NO_COLOR" ]; then
    C_TITLE=$'\e[1;36m'; C_SECTION=$'\e[1;33m'; C_CMD=$'\e[32m'
    C_DIM=$'\e[2m'; C_ERR=$'\e[31m'; C_RESET=$'\e[0m'
else
    C_TITLE=''; C_SECTION=''; C_CMD=''; C_DIM=''; C_ERR=''; C_RESET=''
fi

print_help() {
    echo "${C_TITLE}MyApp stack runner (production / Linux-Mac)${C_RESET}"
    echo "${C_DIM}Usage: ./run.sh <command> [args]${C_RESET}"
    echo ""
    echo "${C_SECTION}Stack${C_RESET}"
    echo "  ${C_CMD}up${C_RESET}                 Start the full stack (api + redis + celery + beat + flower)"
    echo "  ${C_CMD}down${C_RESET}               Stop and remove the stack (with volumes)"
    echo "  ${C_CMD}restart${C_RESET}            Down then up (clean reload of code/config)"
    echo "  ${C_CMD}shell [service]${C_RESET}    Open a shell in a running service (default: api)"
    echo ""
    echo "${C_SECTION}Database${C_RESET}"
    echo "  ${C_CMD}migrate [msg]${C_RESET}      Generate an Alembic migration from model changes"
    echo "  ${C_CMD}upgrade [N]${C_RESET}        Apply migrations (default: all pending)"
    echo "  ${C_CMD}downgrade [N]${C_RESET}      Revert migrations (default: 1 step back)"
    echo "  ${C_CMD}seed [type]${C_RESET}        Run seeds (all|admin|routes|countries)"
    echo ""
    echo "${C_SECTION}Dependencies${C_RESET}"
    echo "  ${C_CMD}lock${C_RESET}               Regenerate uv.lock from pyproject.toml"
    echo "  ${C_CMD}lock-upgrade${C_RESET}       Regenerate uv.lock with upgrades"
    echo ""
    echo "${C_SECTION}Secrets (SOPS + age)${C_RESET}"
    echo "  ${C_CMD}secrets-keygen${C_RESET}     Generate this machine's age key; print the public key"
    echo "  ${C_CMD}secrets-edit${C_RESET}       Edit secrets.enc.env (decrypts in your editor)"
    echo "  ${C_CMD}secrets-rekey${C_RESET}      Re-encrypt secrets.enc.env to current .sops.yaml recipients"
    echo ""
    echo "  ${C_CMD}help${C_RESET}               Show this help (aliases: -h, --help)"
}

require_secrets() {
    command -v sops >/dev/null 2>&1 || { echo "${C_ERR}Error: sops not installed (install sops + age).${C_RESET}"; exit 1; }
    [ -f "$SECRETS_FILE" ] || { echo "${C_ERR}Error: $SECRETS_FILE not found. Run \"./run.sh secrets-keygen\" and get added to .sops.yaml.${C_RESET}"; exit 1; }
}

# Run a compose command with secrets decrypted into its env in-memory (never to disk).
dc() { require_secrets; sops exec-env "$SECRETS_FILE" "docker compose $ENV_FILE_FLAGS $COMPOSE_FILES $*"; }

do_up()   { require_secrets; echo "Starting the full API stack..."; chmod -R 777 logs/ 2>/dev/null || true; dc $PROFILE_FLAGS up --build -d; echo "Started."; }
do_down() { require_secrets; echo "Stopping the full API stack..."; dc $PROFILE_FLAGS down -v; echo "Stopped."; }

case "$1" in
    ""|help|-h|--help) print_help ;;
    up) do_up ;;
    down) do_down ;;
    restart) echo "Restarting..."; do_down; do_up ;;
    shell) SERVICE="${2:-api}"; echo "Opening a shell in '$SERVICE'..."; dc $PROFILE_FLAGS exec "$SERVICE" bash ;;
    lock) docker run --rm -v "$(pwd)":/app -w /app "$UV_IMAGE" uv lock ;;
    lock-upgrade) docker run --rm -v "$(pwd)":/app -w /app "$UV_IMAGE" uv lock --upgrade ;;
    migrate)
        require_secrets; MSG="${2:-auto_migration}"; echo "Migration: $MSG"
        dc run --rm api alembic revision --autogenerate -m "\"$MSG\"" ;;
    upgrade)
        require_secrets; STEPS="${2:-}"
        if [ -z "$STEPS" ]; then dc run --rm api alembic upgrade head
        else dc run --rm api alembic upgrade "+$STEPS"; fi ;;
    downgrade) require_secrets; STEPS="${2:-1}"; dc run --rm api alembic downgrade "-$STEPS" ;;
    seed)
        require_secrets; SEED_TYPE="${2:-}"
        if [ -z "$SEED_TYPE" ]; then dc run --rm api python -m src.seeds.run
        else dc run --rm api python -m src.seeds.run "$SEED_TYPE"; fi ;;
    secrets-keygen)
        command -v age-keygen >/dev/null 2>&1 || { echo "${C_ERR}Error: age not installed.${C_RESET}"; exit 1; }
        if [ -f "$AGE_KEY_FILE" ]; then echo "Key exists at $AGE_KEY_FILE - not overwriting."
        else mkdir -p "$AGE_KEY_DIR"; age-keygen -o "$AGE_KEY_FILE"; echo "Generated $AGE_KEY_FILE. Keep the PRIVATE key secret."; fi
        echo ""; echo "Your PUBLIC key - send it to whoever manages .sops.yaml:"; age-keygen -y "$AGE_KEY_FILE" ;;
    secrets-edit)
        require_secrets
        if command -v code >/dev/null 2>&1; then export EDITOR="code --wait"; fi
        sops "$SECRETS_FILE" ;;
    secrets-rekey)
        command -v sops >/dev/null 2>&1 || { echo "${C_ERR}Error: sops not installed.${C_RESET}"; exit 1; }
        [ -f "$SECRETS_FILE" ] || { echo "${C_ERR}Error: $SECRETS_FILE not found.${C_RESET}"; exit 1; }
        echo "Re-encrypting $SECRETS_FILE to the recipients in .sops.yaml ..."
        sops updatekeys -y "$SECRETS_FILE" ;;
    *) echo "${C_ERR}Error: Invalid command '$1'.${C_RESET}"; echo ""; print_help; exit 1 ;;
esac
```

---

## Appendix C — quick adaptation checklist for the agent

When applying to a new app, change these and nothing else structural:
- [ ] `COMPOSE_FILES` / overlay names; `SECRETS_FILE` stays `secrets.enc.env`.
- [ ] `PROFILE_FLAGS` (drop if the app has no optional profile).
- [ ] DB/seed commands (`alembic ...`, `python -m src.seeds.run`) → the app's real commands.
- [ ] `x-secret-vars` list = exactly the keys in `secrets.enc.env`.
- [ ] `config.env` bucket-B keys; loader (`config.py`) `load_dotenv(config.env)` + `os.getenv`.
- [ ] Title strings in `print_help`.
- [ ] Recipient public keys in `.sops.yaml`.
- [ ] Then run the §7 checklist — especially the §7 item-6 killer test.
