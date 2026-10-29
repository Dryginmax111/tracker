@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title Rollback Patches

set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

rem --- detect project root ---
set "SCRIPTPATH=%~dp0"
if "!SCRIPTPATH:~-1!"=="\" set "SCRIPTPATH=!SCRIPTPATH:~0,-1!"
set "ROOT="
if exist "!SCRIPTPATH!\core\patcher.py" set "ROOT=!SCRIPTPATH!"
if not defined ROOT if exist "!SCRIPTPATH!\..\core\patcher.py" (
    for %%I in ("!SCRIPTPATH!\..") do set "ROOT=%%~fI"
)
if not defined ROOT (
    echo [ERROR] core\patcher.py not found near !SCRIPTPATH!
    pause
    exit /b 1
)

set "CORE=!ROOT!\core"
set "TOOLS=!ROOT!\tools"
set "PATCHER=!CORE!\patcher.py"
set "HELPER=!TOOLS!\rollback_helper.py"

rem --- find python ---
set "PY="
if exist "!ROOT!\runtime\embedded\python313\python.exe" set "PY=!ROOT!\runtime\embedded\python313\python.exe"
if not defined PY for /d %%D in ("!ROOT!\runtime\embedded\python*") do (
    if not defined PY if exist "%%~fD\python.exe" set "PY=%%~fD\python.exe"
)
if not defined PY for /d %%D in ("!ROOT!\runtime\embedded\*") do (
    if not defined PY if exist "%%~fD\python.exe" set "PY=%%~fD\python.exe"
)
if not defined PY (
    echo [ERROR] Python not found under runtime\embedded\
    pause
    exit /b 1
)

if not exist "!PATCHER!" (
    echo [ERROR] Missing: !PATCHER!
    pause
    exit /b 1
)
if not exist "!HELPER!" (
    echo [ERROR] Missing: !HELPER!
    pause
    exit /b 1
)

set "TMP_LIST=%TEMP%\_rollback_list.txt"
set "TMP_REV=%TEMP%\_rollback_rev.txt"

goto :menu

:menu
cls
echo ============================================================
echo   Rollback Patches
echo ============================================================
echo.
echo ROOT: !ROOT!
echo.

rem --- load list ---
"!PY!" "!HELPER!" > "!TMP_LIST!" 2>&1
set "LIST_RC=!ERRORLEVEL!"

findstr /B /C:"NO_JOURNAL" "!TMP_LIST!" >nul 2>&1
if not errorlevel 1 (
    echo Journal not found. No patches applied.
    del "!TMP_LIST!" 2>nul
    pause
    exit /b 0
)

findstr /B /C:"EMPTY" "!TMP_LIST!" >nul 2>&1
if not errorlevel 1 (
    echo Journal is empty. No patches applied.
    del "!TMP_LIST!" 2>nul
    pause
    exit /b 0
)

findstr /B /C:"BAD_JOURNAL" "!TMP_LIST!" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo [ERROR] Journal corrupted:
    type "!TMP_LIST!"
    echo.
    echo Restore from .patches_applied.archive-*.json if available.
    del "!TMP_LIST!" 2>nul
    pause
    exit /b 1
)

if not "!LIST_RC!"=="0" (
    echo.
    echo [ERROR] Failed to read journal ^(rc=!LIST_RC!^)
    type "!TMP_LIST!"
    del "!TMP_LIST!" 2>nul
    pause
    exit /b 1
)

rem --- display list ---
echo Applied patches:
echo.
for /f "tokens=1,2,3,* delims=|" %%A in (!TMP_LIST!) do (
    echo   [%%A] %%B
    echo        %%C  %%D
)
echo.
echo Enter:
echo   1..N    - rollback by list number
echo   <id>    - rollback by exact patch id
echo   ALL     - rollback all ^(reverse order^)
echo   CANCEL  - exit
echo.

set "CHOICE="
set /p "CHOICE=Your choice: "
if not defined CHOICE goto :menu

if /i "!CHOICE!"=="CANCEL" ( del "!TMP_LIST!" 2>nul & exit /b 0 )
if /i "!CHOICE!"=="ALL" goto :rollback_all

rem --- detect numeric? ---
set "IS_NUM="
echo !CHOICE!| findstr /R "^[0-9][0-9]*$" >nul 2>&1
if not errorlevel 1 set "IS_NUM=1"

set "TARGET="
if defined IS_NUM (
    for /f "tokens=*" %%R in ('"!PY!" "!HELPER!" --get-id !CHOICE! 2^>nul') do set "TARGET=%%R"
    if "!TARGET!"=="OUT_OF_RANGE" (
        echo.
        echo [ERROR] Number out of range: !CHOICE!
        del "!TMP_LIST!" 2>nul
        pause
        goto :menu
    )
    if "!TARGET!"=="BAD_NUMBER" set "TARGET="
)
if not defined TARGET set "TARGET=!CHOICE!"

echo.
echo Will rollback: !TARGET!
echo.
set "CONF="
set /p "CONF=Confirm? (y/N): "
if /i not "!CONF!"=="y" (
    echo.
    echo Cancelled.
    del "!TMP_LIST!" 2>nul
    timeout /t 1 /nobreak >nul
    goto :menu
)

echo.
echo Running: patcher.py --rollback !TARGET!
echo ------------------------------------------------------------
"!PY!" "!PATCHER!" --rollback "!TARGET!"
set "ROLL_RC=!ERRORLEVEL!"
echo ------------------------------------------------------------
del "!TMP_LIST!" 2>nul

if not "!ROLL_RC!"=="0" (
    echo.
    echo [FAILED] rollback rc=!ROLL_RC!
    echo.
    pause
    goto :menu
)

echo.
echo [OK] Rolled back: !TARGET!
echo.
echo Note: client_version.json is NOT auto-updated by CLI rollback.
echo       It will recompute on next updater check ^(/plugins/updater/^).
echo.
echo Restart server to apply: Ctrl+C in server window, then START.bat
echo.
pause
goto :menu


:rollback_all
echo.
echo WARNING: This will rollback ALL applied patches in reverse order.
echo.
set "CONF="
set /p "CONF=Confirm? (type YES in caps): "
if /i not "!CONF!"=="YES" (
    echo.
    echo Cancelled.
    del "!TMP_LIST!" 2>nul
    timeout /t 1 /nobreak >nul
    goto :menu
)

"!PY!" "!HELPER!" --list-reversed > "!TMP_REV!" 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to read reversed list
    type "!TMP_REV!"
    del "!TMP_LIST!" "!TMP_REV!" 2>nul
    pause
    goto :menu
)

del "!TMP_LIST!" 2>nul

echo.
echo Rolling back all patches...
echo ------------------------------------------------------------
set /a TOTAL=0
set /a OK=0
set /a FAIL=0
for /f "usebackq delims=" %%X in ("!TMP_REV!") do (
    set /a TOTAL+=1
    echo.
    echo [%%X] !TOTAL!-th
    "!PY!" "!PATCHER!" --rollback "%%X"
    if errorlevel 1 (
        set /a FAIL+=1
        echo   FAILED
    ) else (
        set /a OK+=1
        echo   OK
    )
)
echo ------------------------------------------------------------
del "!TMP_REV!" 2>nul

echo.
echo Rollback ALL summary:
echo   Total:  !TOTAL!
echo   OK:     !OK!
echo   Failed: !FAIL!
echo.
echo Restart server: Ctrl+C in server window, then START.bat
echo.
pause
goto :menu
