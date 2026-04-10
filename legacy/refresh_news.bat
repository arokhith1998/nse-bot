@echo off
title NSE News Refresh (Quick)
cd /d "%~dp0"

echo ============================================
echo  Weekend News Refresh (no full scan needed)
echo ============================================
echo.

set "PY="
where py >nul 2>&1
if %errorlevel%==0 (set "PY=py -3") else (
  where python >nul 2>&1
  if %errorlevel%==0 (set "PY=python")
)
if "%PY%"=="" (echo [ERROR] Python not found. & pause & exit /b 1)

%PY% refresh_news.py

echo.
echo Opening dashboard...
if exist "dashboard.html" start "" "dashboard.html"

echo.
echo Press any key to close...
pause >nul
