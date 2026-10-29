@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Tracker Server

set "ROOT=%~dp0"
set "PY="
for %%D in ("%ROOT%runtime\embedded\python_embed*" "%ROOT%runtime\embedded\python313" "%ROOT%runtime\embedded\*") do (
    if not defined PY if exist "%%~fD\python.exe" set "PY=%%~fD\python.exe"
)
if not defined PY if exist "%ROOT%runtime\embedded\python313\python.exe" set "PY=%ROOT%runtime\embedded\python313\python.exe"

set "TOOLS=%ROOT%tools"

if not defined PY (
    echo [ERROR] Python not found. Check runtime\embedded\
    pause
    exit /b 1
)

if not exist "%TOOLS%\health_check.py" (
    echo [ERROR] tools\health_check.py not found
    pause
    exit /b 1
)


cd /d "%TOOLS%"

echo.
echo ============================================================
echo    H E A L T H   C H E C K
echo ============================================================
echo.


title Health check - running
"!PY!" "%TOOLS%\health_check.py"
set "EXIT_CODE=%ERRORLEVEL%"
echo.
pause
