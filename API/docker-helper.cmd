@echo off
REM A script to manage the API application stack using docker-compose files (Windows version)
REM Usage:
REM   docker-helper.cmd up              - Start API stack (dev mode)
REM   docker-helper.cmd down            - Stop and remove the stack
REM   docker-helper.cmd up-celery       - Start API stack with Celery (dev mode)
REM   docker-helper.cmd encrypt-secrets - Encrypt sensitive values in .env
REM   docker-helper.cmd decrypt-secrets - Decrypt sensitive values in .env

setlocal enabledelayedexpansion
set COMPOSE_FILES=-f docker-compose.yml -f docker-compose.dev.yml

if "%1"=="" (
    echo Error: No command provided.
    echo Usage: %0 {up^|down^|up-celery^|encrypt-secrets^|decrypt-secrets^|migrate^|upgrade^|downgrade^|seed}
    exit /b 1
)

if /i "%1"=="up" (
    echo Starting the API stack in dev mode...
    docker compose %COMPOSE_FILES% up --build -d
    if errorlevel 1 exit /b 1
    echo API stack started successfully.
    exit /b 0
) else if /i "%1"=="down" (
    echo Stopping and removing the API stack...
    docker compose %COMPOSE_FILES% down -v
    if errorlevel 1 exit /b 1
    echo API stack stopped successfully.
    exit /b 0
) else if /i "%1"=="up-celery" (
    echo Starting the API stack with Celery in dev mode...
    docker compose %COMPOSE_FILES% --profile celery up --build -d
    if errorlevel 1 exit /b 1
    echo API stack with Celery started successfully.
    exit /b 0
) else if /i "%1"=="migrate" (
    set "msg=%~2"
    if "!msg!"=="" set "msg=auto_migration"
    echo Generating Alembic migration: !msg!
    docker compose %COMPOSE_FILES% run --rm --entrypoint "alembic revision --autogenerate -m \"!msg!\"" api
    if errorlevel 1 exit /b 1
    echo Migration generated successfully. Restart the stack to apply it.
    exit /b 0
) else if /i "%1"=="upgrade" (
    set "steps=%~2"
    if "!steps!"=="" (
        echo Upgrading database to latest migration...
        docker compose %COMPOSE_FILES% run --rm --entrypoint "alembic upgrade head" api
    ) else (
        echo Upgrading database by !steps! step(s^)...
        docker compose %COMPOSE_FILES% run --rm --entrypoint "alembic upgrade +!steps!" api
    )
    if errorlevel 1 exit /b 1
    echo Database upgrade completed successfully.
    exit /b 0
) else if /i "%1"=="downgrade" (
    set "steps=%~2"
    if "!steps!"=="" set "steps=1"
    echo Downgrading database by !steps! step(s^)...
    docker compose %COMPOSE_FILES% run --rm --entrypoint "alembic downgrade -!steps!" api
    if errorlevel 1 exit /b 1
    echo Database downgrade completed successfully.
    exit /b 0
) else if /i "%1"=="seed" (
    set "seedtype=%~2"
    if "!seedtype!"=="" (
        echo Running all database seeds...
        docker compose %COMPOSE_FILES% run --rm --entrypoint "python -m src.seeds.run" api
    ) else (
        echo Running database seed: !seedtype!
        docker compose %COMPOSE_FILES% run --rm --entrypoint "python -m src.seeds.run !seedtype!" api
    )
    if errorlevel 1 exit /b 1
    echo Seeding completed     successfully.
    exit /b 0
) else if /i "%1"=="encrypt-secrets" (
    echo Encrypting sensitive values in .env...
    docker compose %COMPOSE_FILES% run --rm --no-deps --entrypoint "python manage_secrets.py encrypt" api
    exit /b 0
) else if /i "%1"=="decrypt-secrets" (
    echo Decrypting sensitive values in .env...
    docker compose %COMPOSE_FILES% run --rm --no-deps --entrypoint "python manage_secrets.py decrypt" api
    exit /b 0
) else (
    echo Error: Invalid command '%1'.
    echo Usage: %0 {up^|down^|up-celery^|encrypt-secrets^|decrypt-secrets^|migrate^|upgrade^|downgrade^|seed}
    exit /b 1
)
