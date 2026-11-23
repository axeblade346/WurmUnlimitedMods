@echo off
rem Opens the WOM Viewer with the game's graphics.jar (found through Steam, or the one you picked last time).
cd /d "%~dp0"
where py >nul 2>nul && (py wom_viewer.py & goto :eof)
python wom_viewer.py
if errorlevel 1 pause
