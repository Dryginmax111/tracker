@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title Build Release Bundle

set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

rem --- detect project root: this dir or parent ---
set "SCRIPTPATH=%~dp0"
if "!SCRIPTPATH:~-1!"=="\" set "SCRIPTPATH=!SCRIPTPATH:~0,-1!"

set "ROOT="
if exist "!SCRIPTPATH!\core\patcher.py" set "ROOT=!SCRIPTPATH!"
if not defined ROOT if exist "!SCRIPTPATH!\..\core\patcher.py" (
    for %%I in ("!SCRIPTPATH!\..") do set "ROOT=%%~fI"
)

if not defined ROOT (
    echo [ERROR] Cannot find core\patcher.py
    echo         Script location: !SCRIPTPATH!
    echo         Looked here and in parent dir.
    pause
    exit /b 1
)

set "TOOLS=!ROOT!\tools"
set "CORE=!ROOT!\core"
set "PATCHES=!CORE!\patches"
set "BUNDLE_NAME=bundle-release.json"
set "BUNDLE_FILE=!ROOT!\!BUNDLE_NAME!"

rem --- find python ---
set "PY="
if exist "!ROOT!\runtime\embedded\python313\python.exe" set "PY=!ROOT!\runtime\embedded\python313\python.exe"
if not defined PY if exist "!ROOT!\runtime\embedded\python\python.exe" set "PY=!ROOT!\runtime\embedded\python\python.exe"
if not defined PY (
    for /d %%D in ("!ROOT!\runtime\embedded\python*") do (
        if not defined PY if exist "%%~fD\python.exe" set "PY=%%~fD\python.exe"
    )
)
if not defined PY (
    for /d %%D in ("!ROOT!\runtime\embedded\*") do (
        if not defined PY if exist "%%~fD\python.exe" set "PY=%%~fD\python.exe"
    )
)
if not defined PY (
    echo [ERROR] Python not found under !ROOT!\runtime\embedded\
    pause
    exit /b 1
)

rem --- verify required files ---
if not exist "!TOOLS!\health_check.py" (
    echo [ERROR] Missing: !TOOLS!\health_check.py
    pause
    exit /b 1
)
if not exist "!TOOLS!\build_bundle.py" (
    echo [ERROR] Missing: !TOOLS!\build_bundle.py
    pause
    exit /b 1
)
if not exist "!CORE!\patcher.py" (
    echo [ERROR] Missing: !CORE!\patcher.py
    pause
    exit /b 1
)
if not exist "!PATCHES!" (
    echo [ERROR] Missing: !PATCHES!
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Tracker - Build Release Bundle
echo ============================================================
echo   ROOT:    !ROOT!
echo   PYTHON:  !PY!
echo   PATCHES: !PATCHES!
echo.

rem --- STEP 1: Health check ---
echo ============================================================
echo   [1/4] Health check ^(current state^)
echo ============================================================
echo.
"!PY!" "!TOOLS!\health_check.py"
echo.

rem --- STEP 2: Make patches idempotent ---
echo ============================================================
echo   [2/4] Make patches idempotent ^(optional step^)
echo ============================================================
echo.
if exist "!TOOLS!\make_patches_idempotent.py" (
    "!PY!" "!TOOLS!\make_patches_idempotent.py"
) else (
    echo   SKIP: tools\make_patches_idempotent.py not found
)
echo.

rem --- STEP 3: Dry-run bundle ---
echo ============================================================
echo   [3/4] Dry-run bundle ^(no disk changes^)
echo ============================================================
echo.
"!PY!" "!TOOLS!\build_bundle.py" "!PATCHES!" --dry
set "DRY_RC=!ERRORLEVEL!"
echo.
if not "!DRY_RC!"=="0" (
    echo ============================================================
    echo   FAILED: bundle dry-run rc=!DRY_RC!
    echo ============================================================
    echo.
    echo   Fix the failing patch above and rerun this script.
    pause
    exit /b !DRY_RC!
)
echo   OK: all patches passed dry-run
echo.

rem --- STEP 4: Build bundle ---
echo ============================================================
echo   [4/4] Build bundle: !BUNDLE_NAME!
echo ============================================================
echo.
"!PY!" "!TOOLS!\build_bundle.py" "!PATCHES!" -o "!BUNDLE_FILE!"
set "BUILD_RC=!ERRORLEVEL!"
echo.

if not "!BUILD_RC!"=="0" (
    echo ============================================================
    echo   FAILED: bundle build rc=!BUILD_RC!
    echo ============================================================
    pause
    exit /b !BUILD_RC!
)

if not exist "!BUNDLE_FILE!" (
    echo [ERROR] Bundle not created: !BUNDLE_FILE!
    pause
    exit /b 1
)

for %%F in ("!BUNDLE_FILE!") do set "BUNDLE_SIZE=%%~zF"

echo ============================================================
echo   SUCCESS
echo ============================================================
echo.
echo   Bundle: !BUNDLE_FILE!
echo   Size:   !BUNDLE_SIZE! bytes
echo.
echo   How to apply on a clean 1.0.0 server:
echo.
echo     runtime\embedded\python313\python.exe core\patcher.py !BUNDLE_NAME! --dry
echo     runtime\embedded\python313\python.exe core\patcher.py !BUNDLE_NAME!
echo     then Ctrl+C in server window and START.bat
echo.

pause
exit /b 0
