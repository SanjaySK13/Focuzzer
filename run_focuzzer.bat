@echo off
title Focuzzer - Hardcore Study Lock
cd /d "%~dp0"

echo ========================================================
echo          FOCUZZER: ANTI-DISTRACTION STUDY SENTINEL
echo ========================================================
echo.

:: ── 1. Check if Python is installed ─────────────────────────────────────────
where python >nul 2>nul
if %errorlevel% neq 0 goto :install_python
python --version >nul 2>nul
if %errorlevel% neq 0 goto :install_python
goto :check_deps

:install_python
echo [SETUP] Python not found. Installing Python automatically...
echo.

:: Download Python installer silently via PowerShell
powershell -NoProfile -NonInteractive -Command ^
  "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.13.1/python-3.13.1-amd64.exe' -OutFile '%TEMP%\python_installer.exe' -UseBasicParsing"

if not exist "%TEMP%\python_installer.exe" (
    echo [ERROR] Failed to download Python installer. Check your internet connection.
    pause
    exit /b 1
)

echo [SETUP] Running Python installer silently (this may take 1-2 minutes)...
"%TEMP%\python_installer.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_tcltk=1

:: Refresh PATH in this session so python is now findable
set "PATH=%LOCALAPPDATA%\Programs\Python\Python313;%LOCALAPPDATA%\Programs\Python\Python313\Scripts;%PATH%"

:: Verify install worked
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python installation may have succeeded but needs a restart.
    echo Please close this window and re-run Focuzzer.bat after restarting.
    pause
    exit /b 1
)
echo [SETUP] Python installed successfully!
echo.

:: ── 2. Check and install required packages ───────────────────────────────────
:check_deps
echo [SETUP] Checking required packages...

python -c "import pygame" >nul 2>nul
if %errorlevel% neq 0 (
    echo [SETUP] Installing pygame-ce...
    python -m pip install pygame-ce --quiet
)

python -c "import psutil" >nul 2>nul
if %errorlevel% neq 0 (
    echo [SETUP] Installing psutil...
    python -m pip install psutil --quiet
)

python -c "import win32gui" >nul 2>nul
if %errorlevel% neq 0 (
    echo [SETUP] Installing pywin32...
    python -m pip install pywin32 --quiet
)

echo [SETUP] All dependencies ready.
echo.

:: ── 3. Launch Focuzzer ───────────────────────────────────────────────────────
echo Allowed: NotebookLM, Gemini, WhatsApp + Custom Whitelisted URLs
echo Action on other sites: Piercing Siren + Max Volume
echo Lock: Switch-off button disabled until session ends
echo ========================================================
echo.

python focus_guard.py
if %errorlevel% neq 0 (
    echo.
    echo Focuzzer exited with an error (code %errorlevel%).
    pause
)
