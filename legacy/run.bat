@echo off
title NSE Picks Generator
cd /d "%~dp0"

REM Wrap everything in :main so the final pause ALWAYS runs,
REM even if something inside errors out or exits early.
call :main
echo.
echo ============================================
echo  Script finished. Review messages above.
echo ============================================
echo.
echo Press any key to close this window...
pause >nul
exit /b 0

:main
echo ============================================
echo  NSE Paper-Trading Picks Generator
echo ============================================
echo.
echo [step 1/5] Working folder: %CD%
echo.

REM ---- Step 2: find a working Python ----
echo [step 2/5] Looking for Python...
set "PY="

where py >nul 2>&1
if %errorlevel%==0 (
  set "PY=py -3"
  echo    Found py launcher.
) else (
  where python >nul 2>&1
  if %errorlevel%==0 (
    set "PY=python"
    echo    Found python command.
  )
)

if "%PY%"=="" (
  echo.
  echo [ERROR] Python is not installed or not on PATH.
  echo.
  echo FIX:
  echo   1. Download Python 3.10+ from https://www.python.org/downloads/
  echo   2. IMPORTANT: During install, tick "Add python.exe to PATH".
  echo   3. Close this window, reboot, and try again.
  echo.
  goto :eof
)

echo    Python version:
%PY% --version
if %errorlevel% neq 0 (
  echo    [ERROR] Python is on PATH but failed to run.
  echo    This often means the Microsoft Store Python stub is intercepting the command.
  echo    FIX: open "Manage app execution aliases" in Windows Settings and
  echo         turn OFF "App Installer python.exe" and "App Installer python3.exe".
  goto :eof
)
echo.

REM ---- Step 3: check required packages ----
echo [step 3/5] Checking Python packages (pandas, yfinance, nsepython)...
%PY% -c "import pandas, yfinance, nsepython; print('  all packages present')"
if %errorlevel% neq 0 (
  echo    Packages missing. Installing now — this takes 1-3 minutes on first run.
  echo.
  %PY% -m pip install --upgrade pip
  echo.
  %PY% -m pip install -r requirements.txt
  if %errorlevel% neq 0 (
    echo.
    echo [ERROR] pip install failed. Read the messages above.
    echo Common fixes:
    echo   - Run run.bat as Administrator (right-click, "Run as administrator")
    echo   - Or manually: %PY% -m pip install --user pandas yfinance nsepython
    goto :eof
  )
  echo.
  echo    Dependencies installed successfully.
)
echo.

REM ---- Step 4a: grade yesterday's picks (if any) ----
echo [step 4a] Grading previous picks (learning loop)...
%PY% grade_results.py
echo.

REM ---- Step 4b: fetch latest market news ----
echo [step 4b] Fetching latest India/global market news...
%PY% news_fetch.py
echo.

REM ---- Step 4c: run the picks generator ----
echo [step 4/5] Running generate_picks.py (full NSE scan, ~8-15 min)...
echo --------------------------------------------
%PY% generate_picks.py
set "RC=%errorlevel%"
echo --------------------------------------------
echo.

if not "%RC%"=="0" (
  echo [ERROR] generate_picks.py exited with code %RC%
  echo Read the Python traceback above to diagnose the issue.
  echo Copy the error and share it for a fix.
  goto :eof
)

REM ---- Step 5: open the dashboard ----
echo [step 5/5] Opening dashboard...
if exist "picks.json" (
  echo    picks.json written OK.
  start "" "dashboard.html"
  echo    Dashboard launched in your default browser.
) else (
  echo    [WARNING] picks.json was not created. Script may have failed silently.
)

goto :eof
