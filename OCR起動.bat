@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title OCR Server (Keep this window open / Ctrl+C to stop)
cd /d "%~dp0"
echo ============================================================
echo   OCR Server starting...
echo   Keep this window OPEN while using the app.
echo   To stop: press Ctrl+C  or  close this window.
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found. Please install Python and try again.
  echo.
  pause
  exit /b
)

echo Checking library 'anthropic' (first run may take a moment)...
python -m pip install -q anthropic
if errorlevel 1 (
  echo [ERROR] Failed to install 'anthropic'. Check your internet connection.
  pause
  exit /b
)

echo.
echo Launching OCR server (Ctrl+C to stop)...
echo.
python "%~dp0ocr_server.py"

echo.
echo === Server stopped ===
pause
