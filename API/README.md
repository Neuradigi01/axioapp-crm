# API — Quick Reference

The stack is driven by `run.cmd` (Windows / development) and `run.sh` (Linux / Mac /
production). Both wrap Docker Compose and decrypt secrets in-memory via `sops exec-env`
for each command — no plaintext secrets are ever written to disk. Run `run.cmd help`
(or `./run.sh help`) for the full command list.

> **First time on this machine?** See [Secrets (SOPS + age)](#secrets-sops--age) below
> before starting the stack — you need `sops` + `age`, an age key, and to be listed as a
> recipient in `.sops.yaml`.

## Starting the App

### Windows (Development)

```
run.cmd up
```

### Linux / Mac (Production)

```
./run.sh up
```

`up` starts the **full** stack: api + redis + celery + beat + flower.

### API + Redis only (no background workers)

```
run.cmd up-api        # Windows
./run.sh up-api       # Linux / Mac
```

## Stopping the App

```
run.cmd down          # Windows
./run.sh down         # Linux / Mac
```

## What Happens on Startup

When Docker starts, it automatically:

1. Applies any pending database migrations
2. Seeds the database (super admin + default routes)
3. Starts the API server

You don't need to do anything manually for an existing setup.

---

## Database Migrations

Migrations are **applied automatically** on startup, but **creating** new migrations is a manual step.

### When Do I Need to Create a Migration?

Whenever you change the ORM models — add a column, create a new table, rename a field, etc.

### Step-by-Step

**1. Make sure Docker is running**

```
run.cmd up            # Windows
```

**2. Generate the migration**

```
run.cmd migrate add_phone_column_to_tbl_user_info
```

Keep the message a single `snake_case` token. This creates a new file in
`alembic/versions/`. Review it to make sure it looks correct.

> You can also work inside the container directly:
> `docker exec -it crm-api-1 bash` then `alembic revision --autogenerate -m "..."`.

**3. Apply it**

```
run.cmd upgrade
```

Or just restart the container — it applies automatically on startup.

**4. Commit the migration file to git**

### Rolling Back (Downgrade)

```
run.cmd downgrade           # roll back the last migration
run.cmd downgrade 2         # roll back the last 2
```

For finer control (a specific revision, `base`, history), open a shell inside the
container (`docker exec -it crm-api-1 bash`) and use `alembic` directly:

| What | Command |
|------|---------|
| See current migration | `alembic current` |
| See full history | `alembic history --verbose` |
| Downgrade to a revision | `alembic downgrade abc123def456` |
| Downgrade everything | `alembic downgrade base` |
| Create empty migration (manual SQL) | `alembic revision -m "describe it"` |
| See what SQL a migration would run | `alembic upgrade head --sql` |

### Seeds

Seeds run automatically on startup. To run them on demand:

```
run.cmd seed                # all seeds
run.cmd seed admin          # a specific seed
```

### First-Time Setup (Fresh Database)

If you're starting from scratch with no migration files:

```
run.cmd up
run.cmd migrate initial_tables
run.cmd restart
```

The restart will apply the migration and seed the database.

---

## Running Tests

Tests use a separate database (`<your_db_name>_test`). It is created automatically the first time you run tests — no manual setup needed.

**1. Open a shell inside the container**

```
run.cmd shell             # or: docker exec -it crm-api-1 bash
```

**2. Run all tests**

```
python -m pytest tests/ -v
```

**Run a specific test folder / file:**

```
python -m pytest tests/test_auth/ -v
python -m pytest tests/test_auth/test_login.py -v
```

---

## Secrets (SOPS + age)

Secrets are **not** stored in plaintext. Non-secret config lives in `config.env`
(shared) plus one overlay per environment (committed in the clear); secrets live in one
file per environment, encrypted with
[SOPS](https://github.com/getsops/sops) + [age](https://github.com/FiloSottile/age) and
committed. At runtime `run.cmd` / `run.sh` decrypt them **in memory** and forward them
into the containers — there is no plaintext secrets file on disk. Full design notes:
[`SOPS_INTEGRATION_GUIDE.md`](SOPS_INTEGRATION_GUIDE.md).

### Environments (local / prod)

Each machine picks its environment with a one-word, uncommitted `.environment` file:

```
run.cmd env local           # developer machine
./run.sh env prod           # production server
```

| `.environment` | Config loaded                    | Compose overlay            | Secrets                 |
|----------------|----------------------------------|----------------------------|-------------------------|
| `local`        | `config.env` + `config.local.env` | `docker-compose.local.yml` (adds a local Postgres) | `secrets.local.enc.env` |
| `prod`         | `config.env` + `config.prod.env`  | `docker-compose.prod.yml`  | `secrets.prod.enc.env`  |

Stack and database commands refuse to run without `.environment`. Local runs its own
Postgres container, so a fresh machine needs `run.cmd upgrade` (and `run.cmd seed`) after
the first `run.cmd up`. `run.cmd down` keeps the local database; `run.cmd down reset`
wipes it.

### First-time machine setup

```
run.cmd secrets-install     # install sops + age (winget on Windows / brew / GitHub binaries)
# open a NEW terminal so PATH refreshes, then:
run.cmd secrets-keygen      # generate this machine's age key; prints your age1... PUBLIC key
```

Send your **public** key to whoever manages `.sops.yaml`. They add it and run
`run.cmd secrets-rekey <local|prod>`, then commit the re-keyed file. After that you can decrypt.

### Day-to-day

```
run.cmd secrets-edit        # opens the active env's secrets file decrypted in your editor; re-encrypts on save
run.cmd secrets-edit prod   # same, for a specific env
run.cmd secrets-rekey local # re-encrypt to the current recipients in .sops.yaml
```

> **Never hand-edit `secrets.*.enc.env`** — they have an integrity MAC and per-recipient
> wrapped keys. Change secrets only via `run.cmd secrets-edit`.

The age **private** key (`~/.config/sops/age/keys.txt`) never leaves your machine and is
never committed.

---

## Viewing Logs

```
docker logs crm-api-1
docker logs crm-api-1 -f    # follow (live)
```

## Rebuilding After Code Changes

The `up` command already includes `--build`, so just run:

```
run.cmd restart       # Windows  (down then up)
./run.sh restart      # Linux / Mac
```
