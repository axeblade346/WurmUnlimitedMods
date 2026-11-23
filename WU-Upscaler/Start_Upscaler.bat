@echo off
cd /d "%~dp0"
title WU Upscaler
where python >nul 2>nul
if errorlevel 1 (
  where py >nul 2>nul
  if errorlevel 1 (
    echo Python 3 is needed: get it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^), then start this again.
    pause
    exit /b 1
  )
  py -3 wu_upscaler.py
) else (
  python wu_upscaler.py
)
pause
