#!/bin/bash
# Manage the API application stack (Linux / Mac, production compose files).
# Secrets are decrypted in-memory by `sops exec-env` per command - never written to disk.
# Run `./run.sh help` for the command list.

set -e

ENV_FILE_FLAGS="--env-file config.env"
COMPOSE_FILES="-f docker-compose.yml -f docker-compose.prod.yml"
UV_IMAGE="ghcr.io/astral-sh/uv:0.5-python3.13-bookworm-slim"
SECRETS_FILE="secrets.enc.env"
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
    echo "${C_TITLE}FurnitureCRM API stack runner (production / Linux-Mac)${C_RESET}"
    echo "${C_DIM}Usage: ./run.sh <command> [args]${C_RESET}"
    echo ""
    echo "${C_SECTION}Stack${C_RESET}"
    echo "  ${C_CMD}up${C_RESET}                 Start the full stack (api + redis + celery + beat + flower)"
    echo "  ${C_CMD}up-api${C_RESET}             Start API + Redis only (no celery / beat / flower)"
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
    echo "  ${C_CMD}secrets-install${C_RESET}    Install sops + age (brew on Mac, GitHub binaries on Linux)"
    echo "  ${C_CMD}secrets-keygen${C_RESET}     Generate this machine's age key; print the public key"
    echo "  ${C_CMD}secrets-edit${C_RESET}       Edit secrets.enc.env (decrypts in your editor)"
    echo "  ${C_CMD}secrets-rekey${C_RESET}      Re-encrypt secrets.enc.env to current .sops.yaml recipients"
    echo ""
    echo "  ${C_CMD}help${C_RESET}               Show this help (aliases: -h, --help)"
}

require_secrets() {
    command -v sops >/dev/null 2>&1 || { echo "${C_ERR}Error: sops not installed. Run \"./run.sh secrets-install\" first.${C_RESET}"; exit 1; }
    [ -f "$SECRETS_FILE" ] || { echo "${C_ERR}Error: $SECRETS_FILE not found. Run \"./run.sh secrets-keygen\" and get added to .sops.yaml.${C_RESET}"; exit 1; }
}

# Run a compose command with secrets decrypted into its env in-memory (never to disk).
dc() { require_secrets; sops exec-env "$SECRETS_FILE" "docker compose $ENV_FILE_FLAGS $COMPOSE_FILES $*"; }

APP_DIR="../APP"

# Idempotently point git at the committed hooks (check-then-set). Relative
# core.hooksPath resolves to the working-tree root, so this works from anywhere.
ensure_hooks() {
    if [ "$(git config core.hooksPath 2>/dev/null)" != ".githooks" ]; then
        git config core.hooksPath .githooks && echo "Git hooks enabled (core.hooksPath -> .githooks)."
    fi
}

# Locate the running `api` container (no secrets needed for exec).
api_cid() { docker compose $COMPOSE_FILES ps -q api 2>/dev/null | head -n1; }

do_lint() {
    set +e; rc=0
    CID=$(api_cid)
    if [ -n "$CID" ] && docker exec "$CID" sh -c 'command -v ruff >/dev/null 2>&1'; then
        echo "== ruff format --check (container) =="; docker exec "$CID" ruff format --check src tests || rc=1
        echo "== ruff check (container) ==";          docker exec "$CID" ruff check src tests || rc=1
    else
        echo "Skipping Python lint: dev 'api' container not running (./run.sh up) or ruff not in image."
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
        echo "Skipping Python autofix: dev 'api' container not running or ruff not in image."
    fi
    if [ -d "$APP_DIR/node_modules" ]; then
        echo "== prettier --write (APP) =="; ( cd "$APP_DIR" && npx --no-install prettier --write "src/**/*.{ts,html,scss,css,json}" )
        echo "== eslint --fix (APP) ==";      ( cd "$APP_DIR" && npx --no-install eslint . --fix )
    else
        echo "Skipping frontend autofix: APP/node_modules missing (npm ci)."
    fi
    set -e
}

do_up()     { require_secrets; ensure_hooks; echo "Starting the full API stack..."; chmod -R 777 logs/ 2>/dev/null || true; chmod -R 777 flower/ 2>/dev/null || true; dc --profile celery up --build -d; echo "Started."; }
do_up_api() { require_secrets; ensure_hooks; echo "Starting the API stack (api + redis only)..."; chmod -R 777 logs/ 2>/dev/null || true; dc up --build -d; echo "Started."; }
do_down()   { require_secrets; echo "Stopping the full API stack..."; dc --profile celery down -v; echo "Stopped."; }

case "$1" in
    ""|help|-h|--help) print_help ;;
    up) do_up ;;
    up-api) do_up_api ;;
    down) do_down ;;
    restart) echo "Restarting..."; do_down; do_up ;;
    shell) SERVICE="${2:-api}"; echo "Opening a shell in '$SERVICE'..."; dc exec "$SERVICE" bash ;;
    migrate)
        require_secrets; MSG="${2:-auto_migration}"; echo "Migration: $MSG"
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
        require_secrets
        if command -v code >/dev/null 2>&1; then export EDITOR="code --wait"; fi
        sops "$SECRETS_FILE"
        echo "Saved and re-encrypted. Commit $SECRETS_FILE." ;;
    secrets-rekey)
        command -v sops >/dev/null 2>&1 || { echo "${C_ERR}Error: sops not installed. Run \"./run.sh secrets-install\" first.${C_RESET}"; exit 1; }
        [ -f "$SECRETS_FILE" ] || { echo "${C_ERR}Error: $SECRETS_FILE not found.${C_RESET}"; exit 1; }
        echo "Re-encrypting $SECRETS_FILE to the recipients in .sops.yaml ..."
        sops updatekeys -y "$SECRETS_FILE"
        echo "Done. Commit $SECRETS_FILE." ;;
    *) echo "${C_ERR}Error: Invalid command '$1'.${C_RESET}"; echo ""; print_help; exit 1 ;;
esac
