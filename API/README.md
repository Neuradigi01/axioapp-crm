# API — Quick Reference

## Starting the App

### Windows (Development)

```
docker-helper.cmd up
```

### Linux / Mac (Production)

```
./docker-helper.sh up
```

### With Celery (background tasks)

```
docker-helper.cmd up-celery        # Windows
./docker-helper.sh up-celery       # Linux / Mac
```

## Stopping the App

```
docker-helper.cmd down             # Windows
./docker-helper.sh down            # Linux / Mac
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
docker-helper.cmd up               # Windows
```

**2. Open a shell inside the container**

```
docker exec -it template_api-api-1 bash
```

**3. Generate the migration**

```
alembic revision --autogenerate -m "add phone column to tbl_user_info"
```

This creates a new file in `alembic/versions/`. Review it to make sure it looks correct.

**4. Apply it**

```
alembic upgrade head
```

Or just restart the container — it applies automatically on startup.

**5. Commit the migration file to git**

### Rolling Back (Downgrade)

Open a shell inside the container first:

```
docker exec -it template_api-api-1 bash
```

**Rollback the last migration:**

```
alembic downgrade -1
```

**Rollback the last 2 migrations:**

```
alembic downgrade -2
```

**Rollback to a specific revision:**

```
alembic downgrade abc123def456
```

You can find revision IDs with `alembic history --verbose`.

**Rollback everything (empty database):**

```
alembic downgrade base
```

### Other Useful Commands

Run these inside the container (`docker exec -it template_api-api-1 bash`):

| What | Command |
|------|---------|
| See current migration | `alembic current` |
| See full history | `alembic history --verbose` |
| Create empty migration (manual SQL) | `alembic revision -m "describe it"` |
| Upgrade to a specific revision | `alembic upgrade abc123def456` |
| See what SQL a migration would run | `alembic upgrade head --sql` |

### First-Time Setup (Fresh Database)

If you're starting from scratch with no migration files:

```
docker-helper.cmd up
docker exec -it template_api-api-1 bash
alembic revision --autogenerate -m "initial tables"
exit
docker-helper.cmd down
docker-helper.cmd up
```

The second startup will apply the migration and seed the database.

---

## Running Tests

Tests use a separate database (`<your_db_name>_test`). It is created automatically the first time you run tests — no manual setup needed.

**1. Open a shell inside the container**

```
docker exec -it template_api-api-1 bash
```

**2. Run all tests**

```
python -m pytest tests/ -v
```

**Run a specific test folder:**

```
python -m pytest tests/test_auth/ -v
```

**Run a single test file:**

```
python -m pytest tests/test_auth/test_login.py -v
```

---

## Encrypting .env Secrets

Sensitive values in `.env` can be encrypted so they're not stored in plain text. This protects against malware that scans for `.env` files.

**Encrypt all sensitive values:**

```
docker-helper.cmd encrypt-secrets     # Windows
./docker-helper.sh encrypt-secrets    # Linux / Mac
```

You'll be prompted to enter and confirm a `MASTER_KEY`. This encrypts values like `DB_PASSWORD`, `JWT_SECRET_KEY`, etc. in-place — they'll become `ENC:...` strings in your `.env` file.

**Decrypt back to plain text:**

```
docker-helper.cmd decrypt-secrets     # Windows
./docker-helper.sh decrypt-secrets    # Linux / Mac
```

**Setting MASTER_KEY (never store in `.env` — that defeats the purpose):**

Development (Windows):
```
setx MASTER_KEY "your-master-key"
# Restart VS Code, then docker-compose picks it up via docker-compose.dev.yml
```

Production (VPS — one-time setup, shared across all apps on the server):
```
echo "MASTER_KEY=your-master-key" | sudo tee /etc/master.env
sudo chmod 600 /etc/master.env
# docker-compose.prod.yml reads this file automatically
```

> **Note:** Without `MASTER_KEY`, plain text values still work as before. Encryption is fully opt-in.

---

## Viewing Logs

```
docker logs template_api-api-1
docker logs template_api-api-1 -f    # follow (live)
```

## Rebuilding After Code Changes

The `up` command already includes `--build`, so just run:

```
docker-helper.cmd down && docker-helper.cmd up
```
