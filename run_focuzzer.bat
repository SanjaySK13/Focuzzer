@echo off
title Focuzzer - Hardcore Study Lock
cd /d "%~dp0"

echo ========================================================
echo          FOCUZZER: ANTI-DISTRACTION STUDY SENTINEL
echo ========================================================
echo Allowed: NotebookLM, Gemini, WhatsApp + Custom Whitelisted URLs
echo Action on other sites: Piercing Siren + Max Volume
echo Lock: Switch off button disabled until session ends
echo ========================================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python is not found in your PATH!
    echo Please install Python 3.x and ensure it is added to PATH.
    pause
    exit /b 1
)

python focus_guard.py
if %errorlevel% neq 0 (
    echo.
    echo Focuzzer exited with code %errorlevel%.
    pause
)
