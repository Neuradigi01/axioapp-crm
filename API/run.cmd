@echo off
<<<<<<< HEAD
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
=======
REM Manage the API application stack (Windows).
REM
REM The per-machine .environment file (one word: local | prod, not committed)
REM picks the environment:
REM   local -> config.env + config.local.env, docker-compose.local.yml, secrets.local.enc.env
REM   prod  -> config.env + config.prod.env,  docker-compose.prod.yml,  secrets.prod.enc.env
REM Create or switch it with `run.cmd env local|prod`.
REM
REM Secrets are decrypted in-memory by `sops exec-env` for each stack/DB command
REM and forwarded into containers via the `environment:` passthrough - never
REM written to disk. Run `run.cmd help` for the command list.

setlocal enabledelayedexpansion
set "APP_ENV="
if exist ".environment" for /f "usebackq tokens=1" %%a in (`type .environment`) do if not defined APP_ENV set "APP_ENV=%%a"
set "ENV_FILE_FLAGS=--env-file config.env --env-file config.!APP_ENV!.env"
set "COMPOSE_FILES=-f docker-compose.yml -f docker-compose.!APP_ENV!.yml"
set "SECRETS_FILE=secrets.!APP_ENV!.enc.env"
set UV_IMAGE=ghcr.io/astral-sh/uv:0.5-python3.13-bookworm-slim
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
) else if /i "%1"=="env" ( call :do_env "%~2" & exit /b !errorlevel!
) else if /i "%1"=="up" ( call :do_up & exit /b !errorlevel!
) else if /i "%1"=="up-api" ( call :do_up_api & exit /b !errorlevel!
) else if /i "%1"=="down" ( call :do_down "%~2" & exit /b !errorlevel!
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
    sops exec-env %SECRETS_FILE% "docker compose %ENV_FILE_FLAGS% %COMPOSE_FILES% exec !service! bash"
    exit /b !errorlevel!
) else if /i "%1"=="migrate" (
    call :require_secrets
    if errorlevel 1 exit /b 1
    set "msg=%~2"
    if "!msg!"=="" set "msg=auto_migration"
    echo Generating Alembic migration: !msg!
    sops exec-env %SECRETS_FILE% "docker compose %ENV_FILE_FLAGS% %COMPOSE_FILES% run --rm --entrypoint alembic api revision --autogenerate -m !msg!"
    exit /b !errorlevel!
) else if /i "%1"=="upgrade" (
    call :require_secrets
    if errorlevel 1 exit /b 1
    set "steps=%~2"
    if "!steps!"=="" (
        sops exec-env %SECRETS_FILE% "docker compose %ENV_FILE_FLAGS% %COMPOSE_FILES% run --rm --entrypoint alembic api upgrade head"
    ) else (
        sops exec-env %SECRETS_FILE% "docker compose %ENV_FILE_FLAGS% %COMPOSE_FILES% run --rm --entrypoint alembic api upgrade +!steps!"
    )
    exit /b !errorlevel!
) else if /i "%1"=="downgrade" (
    call :require_secrets
    if errorlevel 1 exit /b 1
    set "steps=%~2"
    if "!steps!"=="" set "steps=1"
    sops exec-env %SECRETS_FILE% "docker compose %ENV_FILE_FLAGS% %COMPOSE_FILES% run --rm --entrypoint alembic api downgrade -!steps!"
    exit /b !errorlevel!
) else if /i "%1"=="seed" (
    call :require_secrets
    if errorlevel 1 exit /b 1
    set "seedtype=%~2"
    if "!seedtype!"=="" (
        sops exec-env %SECRETS_FILE% "docker compose %ENV_FILE_FLAGS% %COMPOSE_FILES% run --rm --entrypoint python api -m src.seeds.run"
    ) else (
        sops exec-env %SECRETS_FILE% "docker compose %ENV_FILE_FLAGS% %COMPOSE_FILES% run --rm --entrypoint python api -m src.seeds.run !seedtype!"
    )
    exit /b !errorlevel!
) else if /i "%1"=="lock" (
    echo Regenerating uv.lock from pyproject.toml...
    docker run --rm -v "%cd%":/app -w /app %UV_IMAGE% uv lock
    exit /b !errorlevel!
) else if /i "%1"=="lock-upgrade" (
    echo Regenerating uv.lock with upgrades...
    docker run --rm -v "%cd%":/app -w /app %UV_IMAGE% uv lock --upgrade
    exit /b !errorlevel!
) else if /i "%1"=="lint" ( call :do_lint & exit /b !errorlevel!
) else if /i "%1"=="lint-fix" ( call :do_lint_fix & exit /b !errorlevel!
) else if /i "%1"=="hooks-on" ( git config core.hooksPath .githooks & echo Git hooks enabled ^(core.hooksPath -^> .githooks^). & exit /b 0
) else if /i "%1"=="hooks-off" ( git config --unset core.hooksPath 2>nul & echo Git hooks disabled ^(using default .git\hooks^). & exit /b 0
) else if /i "%1"=="hooks-status" ( call :hooks_status & exit /b 0
) else if /i "%1"=="secrets-install" (
    set "missing="
    where sops >nul 2>nul
    if errorlevel 1 set "missing=1"
    where age-keygen >nul 2>nul
    if errorlevel 1 set "missing=1"
    if not defined missing (
        echo sops and age are already installed.
        exit /b 0
    )
    where winget >nul 2>nul
    if errorlevel 1 (
        echo %C_ERR%Error: winget not found. Install "App Installer" from the Microsoft Store, then retry.%C_RESET%
        exit /b 1
    )
    echo Installing sops and age via winget...
    winget install --id SecretsOPerationS.SOPS -e --accept-source-agreements --accept-package-agreements
    winget install --id FiloSottile.age -e --accept-source-agreements --accept-package-agreements
    echo.
    echo Installed. Open a NEW terminal so PATH refreshes, then run "run.cmd secrets-keygen".
    exit /b 0
) else if /i "%1"=="secrets-keygen" (
    where age-keygen >nul 2>nul
    if errorlevel 1 ( echo %C_ERR%Error: age not installed. Run "run.cmd secrets-install" first.%C_RESET% & exit /b 1 )
    if exist "%AGE_KEY_FILE%" (
        echo An age key already exists at %AGE_KEY_FILE% - not overwriting.
    ) else (
        if not exist "%AGE_KEY_DIR%" mkdir "%AGE_KEY_DIR%"
        age-keygen -o "%AGE_KEY_FILE%"
        if errorlevel 1 exit /b 1
        echo Key generated at %AGE_KEY_FILE%. Keep the PRIVATE key safe - never commit or share it.
    )
    echo.
    echo Your PUBLIC key - send it to whoever manages .sops.yaml:
    age-keygen -y "%AGE_KEY_FILE%"
    exit /b 0
) else if /i "%1"=="secrets-edit" (
    call :resolve_secrets_target "%~2"
    if errorlevel 1 exit /b 1
    where code >nul 2>nul
    if not errorlevel 1 set "EDITOR=code --wait"
    sops !TARGET_FILE!
    if errorlevel 1 exit /b 1
    echo Saved and re-encrypted. Commit !TARGET_FILE!.
    exit /b 0
) else if /i "%1"=="secrets-rekey" (
    call :resolve_secrets_target "%~2"
    if errorlevel 1 exit /b 1
    echo Re-encrypting !TARGET_FILE! to the recipients in .sops.yaml ...
    sops updatekeys -y !TARGET_FILE!
    if errorlevel 1 exit /b 1
    echo Done. Commit !TARGET_FILE!.
    exit /b 0
) else (
    echo %C_ERR%Error: Invalid command '%1'.%C_RESET%
    echo.
    call :print_help
>>>>>>> f3b2a8dce5f529b28cc81ec1937120c9812280d5
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
echo   down                 Stop and remove stack, KEEP volumes (local DB data preserved)
echo   down reset           Stop and remove stack + WIPE volumes (local DB data lost)
echo   restart              down + up (keeps volumes)
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

<<<<<<< HEAD
=======
:print_help
echo %C_TITLE%CRM API stack runner ^(env: !APP_ENV!, Windows^)%C_RESET%
echo %C_DIM%Usage: run.cmd ^<command^> [args]%C_RESET%
echo.
echo %C_SECTION%Environment%C_RESET%
echo   %C_CMD%env [local^|prod]%C_RESET%   Show or switch this machine's env ^(writes .environment^)
echo.
echo %C_SECTION%Stack%C_RESET%
echo   %C_CMD%up%C_RESET%                 Start the full stack ^(api + redis + celery + beat + flower [+ db if local]^)
echo   %C_CMD%up-api%C_RESET%             Start API + Redis [+ db if local] only ^(no celery / beat / flower^)
echo   %C_CMD%down%C_RESET%               Stop and remove the stack, KEEP volumes ^(local DB data preserved^)
echo   %C_CMD%down reset%C_RESET%         Stop and remove the stack and WIPE volumes ^(local DB data lost^)
echo   %C_CMD%restart%C_RESET%            Down then up ^(clean reload of code/config, keeps volumes^)
echo   %C_CMD%shell [service]%C_RESET%    Open a shell in a running service ^(default: api^)
echo.
echo %C_SECTION%Database%C_RESET%
echo   %C_CMD%migrate [msg]%C_RESET%      Generate an Alembic migration ^(msg: snake_case, default auto_migration^)
echo   %C_CMD%upgrade [N]%C_RESET%        Apply migrations ^(default: all pending^)
echo   %C_CMD%downgrade [N]%C_RESET%      Revert migrations ^(default: 1 step back^)
echo   %C_CMD%seed [type]%C_RESET%        Run seeds ^(default: all^)
echo.
echo %C_SECTION%Dependencies%C_RESET%
echo   %C_CMD%lock%C_RESET%               Regenerate uv.lock from pyproject.toml
echo   %C_CMD%lock-upgrade%C_RESET%       Regenerate uv.lock with upgrades
echo.
echo %C_SECTION%Code quality%C_RESET%
echo   %C_CMD%lint%C_RESET%               Check format + lint ^(ruff in container; prettier/eslint in APP^)
echo   %C_CMD%lint-fix%C_RESET%           Auto-format + autofix ^(ruff --fix; prettier --write; eslint --fix^)
echo   %C_CMD%hooks-on%C_RESET%           Enable the committed pre-commit hook ^(core.hooksPath^)
echo   %C_CMD%hooks-off%C_RESET%          Disable the committed pre-commit hook
echo   %C_CMD%hooks-status%C_RESET%       Show the current git hooks path
echo.
echo %C_SECTION%Secrets ^(SOPS + age^)%C_RESET%
echo   %C_CMD%secrets-install%C_RESET%    Install sops + age via winget ^(open a new terminal after^)
echo   %C_CMD%secrets-keygen%C_RESET%     Generate this machine's age key; print the public key
echo   %C_CMD%secrets-edit [local^|prod]%C_RESET%   Edit secrets.^<env^>.enc.env ^(default: active env^)
echo   %C_CMD%secrets-rekey [local^|prod]%C_RESET%  Re-encrypt secrets.^<env^>.enc.env to current .sops.yaml recipients
echo.
echo   %C_CMD%help%C_RESET%               Show this help ^(aliases: -h, --help^)
goto :eof
>>>>>>> f3b2a8dce5f529b28cc81ec1937120c9812280d5

:require_env
if "!APP_ENV!"=="local" exit /b 0
if "!APP_ENV!"=="prod" exit /b 0
if defined APP_ENV (
    echo %C_ERR%Error: .environment must contain 'local' or 'prod', got '!APP_ENV!'. Fix it with "run.cmd env local".%C_RESET%
) else (
    echo %C_ERR%Error: .environment file missing. Run "run.cmd env local" ^(or "run.cmd env prod" on the server^).%C_RESET%
)
exit /b 1

:require_secrets
<<<<<<< HEAD
call :require_sops
if errorlevel 1 exit /b 1
if not exist "!SECRETS_FILE!" (
    echo ERROR: !SECRETS_FILE! not found.
    exit /b 1
)
exit /b 0

=======
call :require_env
if errorlevel 1 exit /b 1
where sops >nul 2>nul
if errorlevel 1 ( echo %C_ERR%Error: sops not installed. Run "run.cmd secrets-install" first.%C_RESET% & exit /b 1 )
if not exist "%SECRETS_FILE%" ( echo %C_ERR%Error: %SECRETS_FILE% not found. Run "run.cmd secrets-keygen" and get added to .sops.yaml.%C_RESET% & exit /b 1 )
exit /b 0

:resolve_secrets_target
set "TARGET_ENV=%~1"
if not defined TARGET_ENV set "TARGET_ENV=!APP_ENV!"
if not "!TARGET_ENV!"=="local" if not "!TARGET_ENV!"=="prod" (
    echo %C_ERR%Error: secrets target must be 'local' or 'prod', got '!TARGET_ENV!'.%C_RESET%
    exit /b 1
)
set "TARGET_FILE=secrets.!TARGET_ENV!.enc.env"
where sops >nul 2>nul
if errorlevel 1 ( echo %C_ERR%Error: sops not installed. Run "run.cmd secrets-install" first.%C_RESET% & exit /b 1 )
if not exist "!TARGET_FILE!" ( echo %C_ERR%Error: !TARGET_FILE! not found.%C_RESET% & exit /b 1 )
exit /b 0

:do_env
set "NEW_ENV=%~1"
if not defined NEW_ENV (
    if defined APP_ENV ( echo Current env: !APP_ENV! ^(from .environment^). Pass 'local' or 'prod' to change. ) else ( echo No .environment yet. Run "run.cmd env local" ^(or "run.cmd env prod" on the server^). )
    exit /b 0
)
if not "!NEW_ENV!"=="local" if not "!NEW_ENV!"=="prod" (
    echo %C_ERR%Error: env must be 'local' or 'prod', got '!NEW_ENV!'.%C_RESET%
    exit /b 1
)
> .environment echo !NEW_ENV!
echo Switched .environment to '!NEW_ENV!'. Run "run.cmd up" to start the stack in this env.
exit /b 0
>>>>>>> f3b2a8dce5f529b28cc81ec1937120c9812280d5

:do_up
call :require_secrets
if errorlevel 1 exit /b 1
<<<<<<< HEAD
echo Starting FULL stack (env: !APP_ENV!)...
sops exec-env "!SECRETS_FILE!" "docker compose !ENV_FILE_FLAGS! !COMPOSE_FILES! --profile celery up --build -d"
=======
call :ensure_hooks
echo Starting the full API stack ^(env: !APP_ENV!^)...
sops exec-env %SECRETS_FILE% "docker compose %ENV_FILE_FLAGS% %COMPOSE_FILES% --profile celery up --build -d"
>>>>>>> f3b2a8dce5f529b28cc81ec1937120c9812280d5
exit /b !errorlevel!


:do_up_api
call :require_secrets
if errorlevel 1 exit /b 1
<<<<<<< HEAD
echo Starting API stack (env: !APP_ENV!, no celery/beat/flower)...
sops exec-env "!SECRETS_FILE!" "docker compose !ENV_FILE_FLAGS! !COMPOSE_FILES! up --build -d"
=======
call :ensure_hooks
echo Starting the API stack ^(env: !APP_ENV!, api + redis only^)...
sops exec-env %SECRETS_FILE% "docker compose %ENV_FILE_FLAGS% %COMPOSE_FILES% up --build -d"
>>>>>>> f3b2a8dce5f529b28cc81ec1937120c9812280d5
exit /b !errorlevel!


:do_down
if /i "%~2"=="reset" goto :do_down_reset
if not "%~2"=="" (
    echo ERROR: Unknown option '%~2' for down. Use 'down' or 'down reset'.
    exit /b 1
)
goto :do_down_keep


:do_down_keep
call :require_secrets
if errorlevel 1 exit /b 1
<<<<<<< HEAD
echo Stopping stack, KEEPING volumes (env: !APP_ENV!)...
sops exec-env "!SECRETS_FILE!" "docker compose !ENV_FILE_FLAGS! !COMPOSE_FILES! --profile celery down"
exit /b !errorlevel!
=======
if "%~1"=="" (
    echo Stopping the full API stack, keeping volumes ^(env: !APP_ENV!^)...
    sops exec-env %SECRETS_FILE% "docker compose %ENV_FILE_FLAGS% %COMPOSE_FILES% --profile celery down"
    exit /b !errorlevel!
)
if /i "%~1"=="reset" (
    echo Stopping the full API stack and WIPING volumes - local DB data will be lost ^(env: !APP_ENV!^)...
    sops exec-env %SECRETS_FILE% "docker compose %ENV_FILE_FLAGS% %COMPOSE_FILES% --profile celery down -v"
    exit /b !errorlevel!
)
echo %C_ERR%Error: unknown option '%~1' for down. Use "down" or "down reset".%C_RESET%
exit /b 1
>>>>>>> f3b2a8dce5f529b28cc81ec1937120c9812280d5


:do_down_reset
call :require_secrets
if errorlevel 1 exit /b 1
echo Stopping stack + WIPING volumes - local DB data will be lost (env: !APP_ENV!)...
sops exec-env "!SECRETS_FILE!" "docker compose !ENV_FILE_FLAGS! !COMPOSE_FILES! --profile celery down -v"
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

<<<<<<< HEAD

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
=======
:do_lint
set "RC=0"
set "CID="
for /f "delims=" %%i in ('docker compose %ENV_FILE_FLAGS% %COMPOSE_FILES% ps -q api 2^>nul') do set "CID=%%i"
if not defined CID (
    echo Skipping Python lint: dev 'api' container not running ^(run.cmd up^).
) else (
    docker exec !CID! sh -c "command -v ruff >/dev/null 2>&1"
    if errorlevel 1 (
        echo Skipping Python lint: ruff not in image ^(rebuild: run.cmd up^).
    ) else (
        echo == ruff format --check ^(container^) ==
        docker exec !CID! ruff format --check src tests || set "RC=1"
        echo == ruff check ^(container^) ==
        docker exec !CID! ruff check src tests || set "RC=1"
    )
)
if exist "..\APP\node_modules" (
    pushd ..\APP
    echo == prettier --check ^(APP^) ==
    call npx --no-install prettier --check "src/**/*.{ts,html,scss,css,json}" || set "RC=1"
    echo == eslint ^(APP^) ==
    call npx --no-install eslint . || set "RC=1"
    popd
) else (
    echo Skipping frontend lint: APP\node_modules missing ^(npm ci^).
)
exit /b !RC!

:do_lint_fix
set "CID="
for /f "delims=" %%i in ('docker compose %ENV_FILE_FLAGS% %COMPOSE_FILES% ps -q api 2^>nul') do set "CID=%%i"
if not defined CID (
    echo Skipping Python autofix: dev 'api' container not running ^(run.cmd up^).
) else (
    docker exec !CID! sh -c "command -v ruff >/dev/null 2>&1"
    if errorlevel 1 (
        echo Skipping Python autofix: ruff not in image ^(rebuild: run.cmd up^).
    ) else (
        echo == ruff format ^(container^) ==
        docker exec !CID! ruff format src tests
        echo == ruff check --fix ^(container^) ==
        docker exec !CID! ruff check --fix src tests
    )
>>>>>>> f3b2a8dce5f529b28cc81ec1937120c9812280d5
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
