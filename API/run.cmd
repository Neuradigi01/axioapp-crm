@echo off
REM Manage the API application stack (Windows / development compose files).
REM Secrets are decrypted in-memory by `sops exec-env` for each stack/DB command
REM and forwarded into containers via the `environment:` passthrough - never
REM written to disk. Run `run.cmd help` for the command list.

setlocal enabledelayedexpansion
set ENV_FILE_FLAGS=--env-file config.env
set COMPOSE_FILES=-f docker-compose.yml -f docker-compose.dev.yml
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
) else if /i "%1"=="up-api" ( call :do_up_api & exit /b !errorlevel!
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
    call :require_secrets
    if errorlevel 1 exit /b 1
    where code >nul 2>nul
    if not errorlevel 1 set "EDITOR=code --wait"
    sops %SECRETS_FILE%
    if errorlevel 1 exit /b 1
    echo Saved and re-encrypted. Commit %SECRETS_FILE%.
    exit /b 0
) else if /i "%1"=="secrets-rekey" (
    where sops >nul 2>nul
    if errorlevel 1 ( echo %C_ERR%Error: sops not installed. Run "run.cmd secrets-install" first.%C_RESET% & exit /b 1 )
    if not exist "%SECRETS_FILE%" ( echo %C_ERR%Error: %SECRETS_FILE% not found.%C_RESET% & exit /b 1 )
    echo Re-encrypting %SECRETS_FILE% to the recipients in .sops.yaml ...
    sops updatekeys -y %SECRETS_FILE%
    if errorlevel 1 exit /b 1
    echo Done. Commit %SECRETS_FILE%.
    exit /b 0
) else (
    echo %C_ERR%Error: Invalid command '%1'.%C_RESET%
    echo.
    call :print_help
    exit /b 1
)

REM Guard against fall-through into the internal labels below.
exit /b 0

:print_help
echo %C_TITLE%FurnitureCRM API stack runner ^(development / Windows^)%C_RESET%
echo %C_DIM%Usage: run.cmd ^<command^> [args]%C_RESET%
echo.
echo %C_SECTION%Stack%C_RESET%
echo   %C_CMD%up%C_RESET%                 Start the full stack ^(api + redis + celery + beat + flower^)
echo   %C_CMD%up-api%C_RESET%             Start API + Redis only ^(no celery / beat / flower^)
echo   %C_CMD%down%C_RESET%               Stop and remove the stack ^(with volumes^)
echo   %C_CMD%restart%C_RESET%            Down then up ^(clean reload of code/config^)
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
echo %C_SECTION%Secrets ^(SOPS + age^)%C_RESET%
echo   %C_CMD%secrets-install%C_RESET%    Install sops + age via winget ^(open a new terminal after^)
echo   %C_CMD%secrets-keygen%C_RESET%     Generate this machine's age key; print the public key
echo   %C_CMD%secrets-edit%C_RESET%       Edit secrets.enc.env ^(decrypts in your editor^)
echo   %C_CMD%secrets-rekey%C_RESET%      Re-encrypt secrets.enc.env to current .sops.yaml recipients
echo.
echo   %C_CMD%help%C_RESET%               Show this help ^(aliases: -h, --help^)
goto :eof

:require_secrets
where sops >nul 2>nul
if errorlevel 1 ( echo %C_ERR%Error: sops not installed. Run "run.cmd secrets-install" first.%C_RESET% & exit /b 1 )
if not exist "%SECRETS_FILE%" ( echo %C_ERR%Error: %SECRETS_FILE% not found. Run "run.cmd secrets-keygen" and get added to .sops.yaml.%C_RESET% & exit /b 1 )
exit /b 0

:do_up
call :require_secrets
if errorlevel 1 exit /b 1
echo Starting the full API stack...
sops exec-env %SECRETS_FILE% "docker compose %ENV_FILE_FLAGS% %COMPOSE_FILES% --profile celery up --build -d"
exit /b !errorlevel!

:do_up_api
call :require_secrets
if errorlevel 1 exit /b 1
echo Starting the API stack (api + redis only)...
sops exec-env %SECRETS_FILE% "docker compose %ENV_FILE_FLAGS% %COMPOSE_FILES% up --build -d"
exit /b !errorlevel!

:do_down
call :require_secrets
if errorlevel 1 exit /b 1
echo Stopping and removing the full API stack...
sops exec-env %SECRETS_FILE% "docker compose %ENV_FILE_FLAGS% %COMPOSE_FILES% --profile celery down -v"
exit /b !errorlevel!
