@echo off
setlocal enabledelayedexpansion

REM ─── fcmd.cmd — Flutter command wrapper ─────────────────────────
REM Usage: fcmd run [device]    — clean build & run
REM        fcmd build           — clean build APK
REM        fcmd <any>           — pass-through to flutter

cd /d "%~dp0"

if "%1"=="" (
    echo Usage: fcmd ^<command^>
    echo.
    echo Commands:
    echo   run [device]   Clean caches, kill Kotlin daemon, pub get, then flutter run
    echo   build          Clean caches, kill Kotlin daemon, pub get, then flutter build apk
    echo   ^<any^>          Pass-through to flutter ^(e.g., fcmd analyze lib^)
    exit /b 0
)

if /i "%1"=="run" goto :clean_run
if /i "%1"=="build" goto :clean_build
goto :passthrough

:clean_run
    call :do_clean
    echo.
    echo ══════════════════════════════════════════════
    echo   Running app...
    echo ══════════════════════════════════════════════
    echo.
    if "%2"=="" (
        flutter run
    ) else (
        flutter run -d %2
    )
    exit /b %errorlevel%

:clean_build
    call :do_clean
    echo.
    echo ══════════════════════════════════════════════
    echo   Building APK...
    echo ══════════════════════════════════════════════
    echo.
    flutter build apk
    exit /b %errorlevel%

:passthrough
    flutter %*
    exit /b %errorlevel%

:do_clean
    echo.
    echo ══════════════════════════════════════════════
    echo   Step 1/4: Killing Kotlin daemon...
    echo ══════════════════════════════════════════════
    taskkill /F /IM kotlin-daemon.exe >nul 2>&1
    if %errorlevel%==0 (
        echo   Kotlin daemon killed.
    ) else (
        echo   No Kotlin daemon running.
    )

    echo.
    echo ══════════════════════════════════════════════
    echo   Step 2/4: Flutter clean...
    echo ══════════════════════════════════════════════
    flutter clean

    echo.
    echo ══════════════════════════════════════════════
    echo   Step 3/4: Clearing Gradle cache...
    echo ══════════════════════════════════════════════
    if exist "android\.gradle" (
        rmdir /s /q "android\.gradle"
        echo   Gradle cache cleared.
    ) else (
        echo   No Gradle cache to clear.
    )

    echo.
    echo ══════════════════════════════════════════════
    echo   Step 4/4: Flutter pub get...
    echo ══════════════════════════════════════════════
    flutter pub get

    exit /b 0
