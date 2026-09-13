#!/bin/bash
# Manage the API application stack (Linux / Mac).
#
# The `.environment` file (one word: "local" or "prod") drives everything:
#   local -> docker-compose.local.yml + secrets.local.enc.env
#   prod  -> docker-compose.prod.yml  + secrets.prod.enc.env
#
# Secrets are decrypted in-memory by `sops exec-env` per command - never
# written to disk. Run `./run.sh help` for the command list.

set -e

# ─── Environment marker ────────────────────────────────────────────────
if [ ! -f ".environment" ]; then
    echo "ERROR: .environment file missing. Create it with one word:"
    echo "  echo local > .environment      (for local dev)"
    echo "  echo prod  > .environment      (on the deployed server)"
    exit 1
fi
APP_ENV=$(tr -d '[:space:]' < .environment)
if [ "$APP_ENV" != "local" ] && [ "$APP_ENV" != "prod" ]; then
    echo "ERROR: .environment must be 'local' or 'prod', got '$APP_ENV'"
    exit 1
fi
export APP_ENV

# ─── Compose + secrets file paths ─────────────────────────────────────
# --env-file passes both configs so ${DB_USER}/${DB_PASSWORD} etc. resolve
# at YAML parse time (needed for the local Postgres POSTGRES_* vars).
ENV_FILE_FLAGS="--env-file config.env --env-file config.${APP_ENV}.env"
COMPOSE_FILES="-f docker-compose.yml -f docker-compose.${APP_ENV}.yml"
UV_IMAGE="ghcr.io/astral-sh/uv:0.5-python3.13-bookworm-slim"
SECRETS_FILE="secrets.${APP_ENV}.enc.env"
AGE_KEY_DIR="$HOME/.config/sops/age"
AGE_KEY_FILE="$AGE_KEY_DIR/keys.txt"
export SOPS_AGE_KEY_FILE="$AGE_KEY_FILE"

# secrets-install puts sops/age in /usr/local/bin, but under `sudo` the RHEL-family
# secure_path excludes it - make sure this script always finds them.
export PATH="/usr/local/bin:$PATH"

if [ -t 1 ] && [ -z "$NO_COLOR" ]; then
    C_TITLE=$'\e[1;36m'; C_SECTION=$'\e[1;33m'; C_CMD=$'\e[32m'
    C_DIM=$'\e[2m'; C_ERR=$'\e[31m'; C_RESET=$'\e[0m'
else
    C_TITLE=''; C_SECTION=''; C_CMD=''; C_DIM=''; C_ERR=''; C_RESET=''
fi

print_help() {
    echo "${C_TITLE}CRM API stack runner (env: $APP_ENV, Linux/Mac)${C_RESET}"
    echo "${C_DIM}Usage: ./run.sh <command> [args]${C_RESET}"
    echo ""
    echo "${C_SECTION}Environment${C_RESET}"
    echo "  ${C_CMD}env local|prod${C_RESET}     Switch this machine's active env (writes .environment)"
    echo ""
    echo "${C_SECTION}Stack${C_RESET}"
    echo "  ${C_CMD}up${C_RESET}                 Start the full stack (api + redis + celery + beat + flower [+ db if local])"
    echo "  ${C_CMD}up-api${C_RESET}             Start API + Redis [+ db if local] only (no celery / beat / flower)"
    echo "  ${C_CMD}down${C_RESET}               Stop and remove the stack (with volumes)"
    echo "  ${C_CMD}restart${C_RESET}            Down then up (clean reload of code/config)"
    echo "  ${C_CMD}shell [service]${C_RESET}    Open a shell in a running service (default: api)"
    echo ""
    echo "${C_SECTION}Database${C_RESET}"
    echo "  ${C_CMD}migrate [msg]${C_RESET}      Generate an Alembic migration (msg: snake_case, default auto_migration)"
    echo "  ${C_CMD}upgrade [N]${C_RESET}        Apply migrations (default: all pending)"
    echo "  ${C_CMD}downgrade [N]${C_RESET}      Revert migrations (default: 1 step back)"
    echo "  ${C_CMD}seed [type]${C_RESET}        Run seeds (default: all)"
    echo ""
    echo "${C_SECTION}Dependencies${C_RESET}"
    echo "  ${C_CMD}lock${C_RESET}               Regenerate uv.lock from pyproject.toml"
    echo "  ${C_CMD}lock-upgrade${C_RESET}       Regenerate uv.lock with upgrades"
    echo ""
    echo "${C_SECTION}Code quality${C_RESET}"
    echo "  ${C_CMD}lint${C_RESET}               Check format + lint (ruff in container; prettier/eslint in APP)"
    echo "  ${C_CMD}lint-fix${C_RESET}           Auto-format + autofix (ruff --fix; prettier --write; eslint --fix)"
    echo "  ${C_CMD}hooks-on${C_RESET}           Enable the committed pre-commit hook (core.hooksPath)"
    echo "  ${C_CMD}hooks-off${C_RESET}          Disable the committed pre-commit hook"
    echo "  ${C_CMD}hooks-status${C_RESET}       Show the current git hooks path"
    echo ""
    echo "${C_SECTION}Secrets (SOPS + age)${C_RESET}"
    echo "  ${C_CMD}secrets-install${C_RESET}            Install sops + age (brew on Mac, GitHub binaries on Linux)"
    echo "  ${C_CMD}secrets-keygen${C_RESET}             Generate this machine's age key; print the public key"
    echo "  ${C_CMD}secrets-edit [local|prod]${C_RESET}   Edit secrets.<env>.enc.env (default: active env)"
    echo "  ${C_CMD}secrets-rekey [local|prod]${C_RESET}  Re-encrypt to current .sops.yaml recipients"
    echo "  ${C_CMD}secrets-encrypt-local${C_RESET}      One-shot: encrypt a plaintext secrets.local.enc.env (post-scaffold)"
    echo ""
    echo "  ${C_CMD}help${C_RESET}               Show this help (aliases: -h, --help)"
}

resolve_secrets_target() {
    local which="${1:-$APP_ENV}"
    case "$which" in
        local) TARGET_FILE="secrets.local.enc.env" ;;
        prod)  TARGET_FILE="secrets.prod.enc.env" ;;
        *) echo "${C_ERR}Error: secrets target must be 'local' or 'prod', got '$which'${C_RESET}"; return 1 ;;
    esac
}

require_secrets_file() {
    command -v sops >/dev/null 2>&1 || { echo "${C_ERR}Error: sops not installed. Run \"./run.sh secrets-install\" first.${C_RESET}"; exit 1; }
    [ -f "$1" ] || { echo "${C_ERR}Error: $1 not found. Run \"./run.sh secrets-keygen\" and get added to .sops.yaml.${C_RESET}"; exit 1; }
}

require_secrets() { require_secrets_file "$SECRETS_FILE"; }

# Run a compose command with secrets decrypted into its env in-memory (never to disk).
dc() { require_secrets; sops exec-env "$SECRETS_FILE" "docker compose $ENV_FILE_FLAGS $COMPOSE_FILES $*"; }

APP_DIR="../APP"

# Idempotently point git at the committed hooks (check-then-set). Relative
# core.hooksPath resolves to the working-tree root, so this works from anywhere.
# No-op when not inside a git work tree (e.g. a deploy target without .git) so
# it never aborts the stack under `set -e`.
ensure_hooks() {
    git rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 0
    if [ "$(git config core.hooksPath 2>/dev/null)" != ".githooks" ]; then
        git config core.hooksPath .githooks && echo "Git hooks enabled (core.hooksPath -> .githooks)."
    fi
}

# Locate the running `api` container (no secrets needed for exec).
api_cid() { docker compose $COMPOSE_FILES ps -q api 2>/dev/null | head -n1; }

# Bind-mounted host dirs (compose `volumes:`) must exist and be owned by the
# container user (appuser, uid/gid 1000 per the Dockerfile) BEFORE `up`.
# Otherwise the docker daemon creates them root-owned and the api worker dies
# on boot (PermissionError: './static/uploads'). Ownership only matters on
# Linux; Docker Desktop on Mac maps host file permissions itself.
APP_UID=1000
APP_GID=1000
ensure_dirs() {
    mkdir -p static/uploads logs flower 2>/dev/null \
        || sudo mkdir -p static/uploads logs flower
    [ "$(uname -s)" = "Linux" ] || return 0
    for d in static logs flower; do
        owner="$(ls -ldn "$d" | awk '{print $3}')"
        if [ "$owner" != "$APP_UID" ]; then
            echo "Fixing ownership of ./$d (uid $owner -> $APP_UID, container appuser)..."
            chown -R "$APP_UID:$APP_GID" "$d" 2>/dev/null \
                || sudo chown -R "$APP_UID:$APP_GID" "$d"
        fi
    done
}

do_env() {
    local target="${1:-}"
    if [ -z "$target" ]; then
        echo "Current env: $APP_ENV (from .environment). Pass 'local' or 'prod' to change."
        return 0
    fi
    case "$target" in
        local|prod) ;;
        *) echo "${C_ERR}Error: env must be 'local' or 'prod', got '$target'${C_RESET}"; return 1 ;;
    esac
    printf '%s\n' "$target" > .environment
    echo "Switched .environment to '$target'. Run \`./run.sh up\` to bring the stack up in the new env."
}

do_lint() {
    set +e; rc=0
    CID=$(api_cid)
    if [ -n "$CID" ] && docker exec "$CID" sh -c 'command -v ruff >/dev/null 2>&1'; then
        echo "== ruff format --check (container) =="; docker exec "$CID" ruff format --check src tests || rc=1
        echo "== ruff check (container) ==";          docker exec "$CID" ruff check src tests || rc=1
    else
        echo "Skipping Python lint: 'api' container not running (./run.sh up) or ruff not in image."
    fi
    if [ -d "$APP_DIR/node_modules" ]; then
        echo "== prettier --check (APP) =="; ( cd "$APP_DIR" && npx --no-install prettier --check "src/**/*.{ts,html,scss,css,json}" ) || rc=1
        echo "== eslint (APP) ==";           ( cd "$APP_DIR" && npx --no-install eslint . ) || rc=1
    else
        echo "Skipping frontend lint: APP/node_modules missing (npm ci)."
    fi
    set -e; return $rc
}

do_lint_fix() {
    set +e
    CID=$(api_cid)
    if [ -n "$CID" ] && docker exec "$CID" sh -c 'command -v ruff >/dev/null 2>&1'; then
        echo "== ruff format (container) ==";    docker exec "$CID" ruff format src tests
        echo "== ruff check --fix (container) =="; docker exec "$CID" ruff check --fix src tests
    else
        echo "Skipping Python autofix: 'api' container not running or ruff not in image."
    fi
    if [ -d "$APP_DIR/node_modules" ]; then
        echo "== prettier --write (APP) =="; ( cd "$APP_DIR" && npx --no-install prettier --write "src/**/*.{ts,html,scss,css,json}" )
        echo "== eslint --fix (APP) ==";      ( cd "$APP_DIR" && npx --no-install eslint . --fix )
    else
        echo "Skipping frontend autofix: APP/node_modules missing (npm ci)."
    fi
    set -e
}

do_up()     { require_secrets; ensure_hooks; ensure_dirs; echo "Starting the full API stack (env: $APP_ENV)..."; dc --profile celery up --build -d; echo "Started."; }
do_up_api() { require_secrets; ensure_hooks; ensure_dirs; echo "Starting the API stack (env: $APP_ENV, api + redis [+ db if local] only)..."; dc up --build -d; echo "Started."; }
do_down()   { require_secrets; echo "Stopping the full API stack (env: $APP_ENV)..."; dc --profile celery down -v; echo "Stopped."; }

case "$1" in
    ""|help|-h|--help) print_help ;;
    env) do_env "${2:-}" ;;
    up) do_up ;;
    up-api) do_up_api ;;
    down) do_down ;;
    restart) echo "Restarting (env: $APP_ENV)..."; do_down; do_up ;;
    shell) SERVICE="${2:-api}"; echo "Opening a shell in '$SERVICE' (env: $APP_ENV)..."; dc exec "$SERVICE" bash ;;
    migrate)
        require_secrets; MSG="${2:-auto_migration}"; echo "Migration (env: $APP_ENV): $MSG"
        dc run --rm --entrypoint alembic api revision --autogenerate -m "$MSG" ;;
    upgrade)
        require_secrets; STEPS="${2:-}"
        if [ -z "$STEPS" ]; then dc run --rm --entrypoint alembic api upgrade head
        else dc run --rm --entrypoint alembic api upgrade "+$STEPS"; fi ;;
    downgrade) require_secrets; STEPS="${2:-1}"; dc run --rm --entrypoint alembic api downgrade "-$STEPS" ;;
    seed)
        require_secrets; SEED_TYPE="${2:-}"
        if [ -z "$SEED_TYPE" ]; then dc run --rm --entrypoint python api -m src.seeds.run
        else dc run --rm --entrypoint python api -m src.seeds.run "$SEED_TYPE"; fi ;;
    lock) docker run --rm -v "$(pwd)":/app -w /app "$UV_IMAGE" uv lock ;;
    lock-upgrade) docker run --rm -v "$(pwd)":/app -w /app "$UV_IMAGE" uv lock --upgrade ;;
    lint) do_lint ;;
    lint-fix) do_lint_fix ;;
    hooks-on) git config core.hooksPath .githooks && echo "Git hooks enabled (core.hooksPath -> .githooks)." ;;
    hooks-off) git config --unset core.hooksPath 2>/dev/null || true; echo "Git hooks disabled (using default .git/hooks)." ;;
    hooks-status) echo "core.hooksPath = $(git config core.hooksPath 2>/dev/null || echo '(default .git/hooks)')" ;;
    secrets-install)
        if command -v sops >/dev/null 2>&1 && command -v age-keygen >/dev/null 2>&1; then
            echo "sops and age are already installed."; exit 0
        fi
        if command -v brew >/dev/null 2>&1; then
            echo "Installing sops and age via Homebrew..."
            brew install sops age
        else
            # Any Linux (apt/dnf/yum/...): official GitHub release binaries into /usr/local/bin.
            SOPS_VERSION="3.13.1"
            AGE_VERSION="1.3.1"
            ARCH=$(uname -m)
            case "$ARCH" in
                x86_64) ARCH=amd64 ;;
                aarch64|arm64) ARCH=arm64 ;;
                *) echo "Unsupported architecture: $ARCH"; exit 1 ;;
            esac
            command -v curl >/dev/null 2>&1 || { echo "Error: curl is required."; exit 1; }
            SUDO="sudo"
            if [ "$(id -u)" -eq 0 ]; then SUDO=""; fi
            if ! command -v sops >/dev/null 2>&1; then
                echo "Installing sops v${SOPS_VERSION} from GitHub releases..."
                $SUDO curl -fsSL -o /usr/local/bin/sops \
                    "https://github.com/getsops/sops/releases/download/v${SOPS_VERSION}/sops-v${SOPS_VERSION}.linux.${ARCH}"
                $SUDO chmod +x /usr/local/bin/sops
            fi
            if ! command -v age-keygen >/dev/null 2>&1; then
                echo "Installing age v${AGE_VERSION} from GitHub releases..."
                AGE_TMP=$(mktemp -d)
                curl -fsSL "https://github.com/FiloSottile/age/releases/download/v${AGE_VERSION}/age-v${AGE_VERSION}-linux-${ARCH}.tar.gz" \
                    | tar -xz -C "$AGE_TMP"
                $SUDO install -m 0755 "$AGE_TMP/age/age" "$AGE_TMP/age/age-keygen" /usr/local/bin/
                rm -rf "$AGE_TMP"
            fi
        fi
        sops --version
        age-keygen --version
        echo "Done. Next: ./run.sh secrets-keygen" ;;
    secrets-keygen)
        command -v age-keygen >/dev/null 2>&1 || { echo "${C_ERR}Error: age not installed. Run \"./run.sh secrets-install\" first.${C_RESET}"; exit 1; }
        if [ -f "$AGE_KEY_FILE" ]; then echo "An age key already exists at $AGE_KEY_FILE - not overwriting."
        else mkdir -p "$AGE_KEY_DIR"; age-keygen -o "$AGE_KEY_FILE"; echo "Key generated at $AGE_KEY_FILE. Keep the PRIVATE key safe - never commit or share it."; fi
        echo ""; echo "Your PUBLIC key - send it to whoever manages .sops.yaml:"; age-keygen -y "$AGE_KEY_FILE" ;;
    secrets-edit)
        resolve_secrets_target "${2:-}" || exit 1
        require_secrets_file "$TARGET_FILE"
        if command -v code >/dev/null 2>&1; then export EDITOR="code --wait"; fi
        sops "$TARGET_FILE"
        echo "Saved and re-encrypted. Commit $TARGET_FILE." ;;
    secrets-rekey)
        command -v sops >/dev/null 2>&1 || { echo "${C_ERR}Error: sops not installed. Run \"./run.sh secrets-install\" first.${C_RESET}"; exit 1; }
        resolve_secrets_target "${2:-}" || exit 1
        [ -f "$TARGET_FILE" ] || { echo "${C_ERR}Error: $TARGET_FILE not found.${C_RESET}"; exit 1; }
        echo "Re-encrypting $TARGET_FILE to the recipients in .sops.yaml ..."
        sops updatekeys -y "$TARGET_FILE"
        echo "Done. Commit $TARGET_FILE." ;;
    secrets-encrypt-local)
        command -v sops >/dev/null 2>&1 || { echo "${C_ERR}Error: sops not installed. Run \"./run.sh secrets-install\" first.${C_RESET}"; exit 1; }
        [ -f "secrets.local.enc.env" ] || { echo "${C_ERR}Error: secrets.local.enc.env not found.${C_RESET}"; exit 1; }
        if grep -q "^sops_version" secrets.local.enc.env 2>/dev/null; then
            echo "secrets.local.enc.env is already encrypted. Nothing to do."; exit 0
        fi
        echo "Encrypting secrets.local.enc.env in-place with SOPS..."
        sops -e -i secrets.local.enc.env
        echo "Done. Commit secrets.local.enc.env." ;;
    *) echo "${C_ERR}Error: Invalid command '$1'.${C_RESET}"; echo ""; print_help; exit 1 ;;
esac
