@echo off
REM Manage the CRM API stack (Windows).
REM .environment (one word: local | prod | prod-neuradigi) drives everything:
REM   local          -> docker-compose.local.yml          + secrets.local.enc.env
REM   prod           -> docker-compose.prod.yml           + secrets.prod.enc.env           (aixoapp.com)
REM   prod-neuradigi -> docker-compose.prod-neuradigi.yml + secrets.prod-neuradigi.enc.env (neuradigi.com)
REM Secrets are decrypted in-memory by 'sops exec-env'; never on disk.

setlocal enabledelayedexpansion

if not exist ".environment" (
    echo ERROR: .environment file missing. Create it with one word:
    echo   echo local^> .environment
    exit /b 1
)

set /p APP_ENV=<.environment
for /f "tokens=*" %%a in ("!APP_ENV!") do set "APP_ENV=%%a"

if /i not "!APP_ENV!"=="local" if /i not "!APP_ENV!"=="prod" if /i not "!APP_ENV!"=="prod-neuradigi" (
    echo ERROR: .environment must be 'local', 'prod', or 'prod-neuradigi', got '!APP_ENV!'
    exit /b 1
)

set "SECRETS_FILE=secrets.!APP_ENV!.enc.env"
set "COMPOSE_FILES=-f docker-compose.yml -f docker-compose.!APP_ENV!.yml"
set "ENV_FILE_FLAGS=--env-file config.env --env-file config.!APP_ENV!.env"
set "UV_IMAGE=ghcr.io/astral-sh/uv:0.5-python3.13-bookworm-slim"
set "AGE_KEY_FILE=%USERPROFILE%\.config\sops\age\keys.txt"
set "SOPS_AGE_KEY_FILE=%AGE_KEY_FILE%"

set "CMD=%1"
if "%CMD%"=="" set "CMD=help"

if /i "%CMD%"=="help"           goto :help
if /i "%CMD%"=="-h"             goto :help
if /i "%CMD%"=="--help"         goto :help
if /i "%CMD%"=="env"            goto :do_env
if /i "%CMD%"=="up"             goto :do_up
if /i "%CMD%"=="up-api"         goto :do_up_api
if /i "%CMD%"=="down"           goto :do_down
if /i "%CMD%"=="down-keep"      goto :do_down_keep
if /i "%CMD%"=="restart"        goto :do_restart
if /i "%CMD%"=="logs"           goto :do_logs
if /i "%CMD%"=="shell"          goto :do_shell
if /i "%CMD%"=="ps"             goto :do_ps
if /i "%CMD%"=="migrate"        goto :do_migrate
if /i "%CMD%"=="upgrade"        goto :do_upgrade
if /i "%CMD%"=="downgrade"      goto :do_downgrade
if /i "%CMD%"=="seed"           goto :do_seed
if /i "%CMD%"=="storage-migrate" goto :do_storage_migrate
if /i "%CMD%"=="lock"           goto :do_lock
if /i "%CMD%"=="secrets-edit"   goto :do_secrets_edit
if /i "%CMD%"=="secrets-rekey"  goto :do_secrets_rekey
if /i "%CMD%"=="secrets-keygen" goto :do_secrets_keygen
if /i "%CMD%"=="secrets-encrypt-local" goto :do_secrets_encrypt_local

echo ERROR: Unknown command '%CMD%'.
echo.
goto :help


:help
echo CRM API stack runner (env: !APP_ENV!, Windows)
echo Usage: run.cmd ^<command^> [args]
echo.
echo Environment
echo   env local^|prod^|prod-neuradigi  Switch this machine's active env (writes .environment)
echo.
echo Stack
echo   up                   Start full stack (api + redis + celery + beat + flower [+ db if local])
echo   up-api               Start api + redis [+ db if local] only
echo   down                 Stop and remove stack + WIPE volumes (local DB data lost)
echo   down-keep            Stop and remove stack, KEEP volumes (local DB data preserved)
echo   restart              down-keep + up
echo   logs [service]       Follow logs (default: api)
echo   shell [service]      Open bash shell in service (default: api)
echo   ps                   Show running containers
echo.
echo Database
echo   migrate [msg]        Generate an Alembic migration (default msg: auto_migration)
echo   upgrade [N]          Apply migrations (default: all pending)
echo   downgrade [N]        Revert migrations (default: 1 step back)
echo   seed [type]          Run seeds (default: all)
echo   storage-migrate [--dry-run] [--only-missing] [--reverse]
echo                        Copy ./storage to the env's R2 bucket (--reverse: back to disk)
echo.
echo Dependencies
echo   lock                 Regenerate uv.lock from pyproject.toml
echo.
echo Secrets (SOPS + age)
echo   secrets-keygen               Generate this machine's age keypair; print public key
echo   secrets-edit [local^|prod^|prod-neuradigi]    Edit a secrets file (default: active env)
echo   secrets-rekey [local^|prod^|prod-neuradigi]   Re-encrypt to current .sops.yaml recipients
echo   secrets-encrypt-local        Encrypt a plaintext secrets.local.enc.env in place
echo.
echo   help                 Show this help
exit /b 0


:do_env
set "target=%~2"
if "%target%"=="" (
    echo Current env: !APP_ENV! ^(from .environment^)
    echo Pass 'local', 'prod', or 'prod-neuradigi' to change.
    exit /b 0
)
if /i not "%target%"=="local" if /i not "%target%"=="prod" if /i not "%target%"=="prod-neuradigi" (
    echo ERROR: env must be 'local', 'prod', or 'prod-neuradigi', got '%target%'
    exit /b 1
)
> .environment echo %target%
echo Switched .environment to '%target%'.
exit /b 0


:require_sops
where sops >nul 2>nul
if errorlevel 1 (
    echo ERROR: sops not installed. Install SOPS + age first.
    exit /b 1
)
exit /b 0


:require_secrets
call :require_sops
if errorlevel 1 exit /b 1
if not exist "!SECRETS_FILE!" (
    echo ERROR: !SECRETS_FILE! not found.
    exit /b 1
)
exit /b 0


:do_up
call :require_secrets
if errorlevel 1 exit /b 1
echo Starting FULL stack (env: !APP_ENV!)...
sops exec-env "!SECRETS_FILE!" "docker compose !ENV_FILE_FLAGS! !COMPOSE_FILES! --profile celery up --build -d"
exit /b !errorlevel!


:do_up_api
call :require_secrets
if errorlevel 1 exit /b 1
echo Starting API stack (env: !APP_ENV!, no celery/beat/flower)...
sops exec-env "!SECRETS_FILE!" "docker compose !ENV_FILE_FLAGS! !COMPOSE_FILES! up --build -d"
exit /b !errorlevel!


:do_down
call :require_secrets
if errorlevel 1 exit /b 1
echo Stopping stack + WIPING volumes (env: !APP_ENV!)...
sops exec-env "!SECRETS_FILE!" "docker compose !ENV_FILE_FLAGS! !COMPOSE_FILES! --profile celery down -v"
exit /b !errorlevel!


:do_down_keep
call :require_secrets
if errorlevel 1 exit /b 1
echo Stopping stack, KEEPING volumes (env: !APP_ENV!)...
sops exec-env "!SECRETS_FILE!" "docker compose !ENV_FILE_FLAGS! !COMPOSE_FILES! --profile celery down"
exit /b !errorlevel!


:do_restart
call :do_down_keep
if errorlevel 1 exit /b 1
call :do_up
exit /b !errorlevel!


:do_logs
set "service=%~2"
if "%service%"=="" set "service=api"
docker compose !COMPOSE_FILES! logs -f !service!
exit /b !errorlevel!


:do_shell
call :require_secrets
if errorlevel 1 exit /b 1
set "service=%~2"
if "%service%"=="" set "service=api"
sops exec-env "!SECRETS_FILE!" "docker compose !ENV_FILE_FLAGS! !COMPOSE_FILES! exec !service! bash"
exit /b !errorlevel!


:do_ps
docker compose !COMPOSE_FILES! ps
exit /b !errorlevel!


:do_migrate
call :require_secrets
if errorlevel 1 exit /b 1
set "msg=%~2"
if "%msg%"=="" set "msg=auto_migration"
echo Generating Alembic migration: !msg!
sops exec-env "!SECRETS_FILE!" "docker compose !ENV_FILE_FLAGS! !COMPOSE_FILES! run --rm --entrypoint alembic api revision --autogenerate -m !msg!"
exit /b !errorlevel!


:do_upgrade
call :require_secrets
if errorlevel 1 exit /b 1
set "steps=%~2"
if "%steps%"=="" (
    sops exec-env "!SECRETS_FILE!" "docker compose !ENV_FILE_FLAGS! !COMPOSE_FILES! run --rm --entrypoint alembic api upgrade head"
) else (
    sops exec-env "!SECRETS_FILE!" "docker compose !ENV_FILE_FLAGS! !COMPOSE_FILES! run --rm --entrypoint alembic api upgrade +!steps!"
)
exit /b !errorlevel!


:do_downgrade
call :require_secrets
if errorlevel 1 exit /b 1
set "steps=%~2"
if "%steps%"=="" set "steps=1"
sops exec-env "!SECRETS_FILE!" "docker compose !ENV_FILE_FLAGS! !COMPOSE_FILES! run --rm --entrypoint alembic api downgrade -!steps!"
exit /b !errorlevel!


:do_seed
call :require_secrets
if errorlevel 1 exit /b 1
set "seedtype=%~2"
if "%seedtype%"=="" (
    sops exec-env "!SECRETS_FILE!" "docker compose !ENV_FILE_FLAGS! !COMPOSE_FILES! run --rm --entrypoint python api -m src.seeds.run"
) else (
    sops exec-env "!SECRETS_FILE!" "docker compose !ENV_FILE_FLAGS! !COMPOSE_FILES! run --rm --entrypoint python api -m src.seeds.run !seedtype!"
)
exit /b !errorlevel!


:do_storage_migrate
call :require_secrets
if errorlevel 1 exit /b 1
sops exec-env "!SECRETS_FILE!" "docker compose !ENV_FILE_FLAGS! !COMPOSE_FILES! run --rm --entrypoint python api -m src.app.shared.storage.migrate %~2 %~3 %~4"
exit /b !errorlevel!


:do_lock
docker run --rm -v "%cd%":/app -w /app %UV_IMAGE% uv lock
exit /b !errorlevel!


:do_secrets_keygen
where age-keygen >nul 2>nul
if errorlevel 1 (
    echo ERROR: age not installed.
    exit /b 1
)
if exist "%AGE_KEY_FILE%" (
    echo Age key already exists at %AGE_KEY_FILE% - not overwriting.
) else (
    if not exist "%USERPROFILE%\.config\sops\age" mkdir "%USERPROFILE%\.config\sops\age"
    age-keygen -o "%AGE_KEY_FILE%"
)
echo.
echo Your PUBLIC key - send it to whoever manages .sops.yaml:
age-keygen -y "%AGE_KEY_FILE%"
exit /b 0


:do_secrets_edit
call :require_sops
if errorlevel 1 exit /b 1
set "which=%~2"
if "%which%"=="" set "which=!APP_ENV!"
if /i "%which%"=="local"          set "TARGET=secrets.local.enc.env"
if /i "%which%"=="prod"           set "TARGET=secrets.prod.enc.env"
if /i "%which%"=="prod-neuradigi" set "TARGET=secrets.prod-neuradigi.enc.env"
if not defined TARGET (
    echo ERROR: secrets target must be 'local', 'prod', or 'prod-neuradigi', got '%which%'
    exit /b 1
)
if not exist "!TARGET!" ( echo ERROR: !TARGET! not found. & exit /b 1 )
where code >nul 2>nul
if not errorlevel 1 set "EDITOR=code --wait"
sops !TARGET!
if errorlevel 1 exit /b 1
echo Saved and re-encrypted. Commit !TARGET!.
exit /b 0


:do_secrets_rekey
call :require_sops
if errorlevel 1 exit /b 1
set "which=%~2"
if "%which%"=="" set "which=!APP_ENV!"
if /i "%which%"=="local"          set "TARGET=secrets.local.enc.env"
if /i "%which%"=="prod"           set "TARGET=secrets.prod.enc.env"
if /i "%which%"=="prod-neuradigi" set "TARGET=secrets.prod-neuradigi.enc.env"
if not defined TARGET (
    echo ERROR: secrets target must be 'local', 'prod', or 'prod-neuradigi', got '%which%'
    exit /b 1
)
if not exist "!TARGET!" ( echo ERROR: !TARGET! not found. & exit /b 1 )
echo Re-encrypting !TARGET! to current .sops.yaml recipients...
sops updatekeys -y !TARGET!
exit /b !errorlevel!


:do_secrets_encrypt_local
call :require_sops
if errorlevel 1 exit /b 1
if not exist "secrets.local.enc.env" ( echo ERROR: secrets.local.enc.env not found. & exit /b 1 )
findstr /R /C:"^sops_version" secrets.local.enc.env >nul 2>nul
if not errorlevel 1 (
    echo secrets.local.enc.env is already encrypted. Nothing to do.
    exit /b 0
)
echo Encrypting secrets.local.enc.env in place with SOPS...
sops -e -i secrets.local.enc.env
if errorlevel 1 exit /b 1
echo Done. Commit secrets.local.enc.env.
exit /b 0
