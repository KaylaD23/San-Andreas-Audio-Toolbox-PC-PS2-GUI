@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 SAAT_PS2_Studio.py
) else (
  python SAAT_PS2_Studio.py
)
if errorlevel 1 pause
