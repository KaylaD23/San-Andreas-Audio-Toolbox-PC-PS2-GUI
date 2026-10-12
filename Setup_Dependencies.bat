@echo off
cd /d "%~dp0"
echo Installing dependencies for San Andreas Audio Toolbox PC/PS2 GUI...
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m pip install -r requirements.txt
) else (
  python -m pip install -r requirements.txt
)
if errorlevel 1 (
  echo.
  echo Dependency installation failed. Install Python with pip, then run:
  echo python -m pip install -r requirements.txt
  pause
  exit /b 1
)
echo.
echo Done. Re-launch San Andreas Audio Toolbox PC/PS2 GUI.
pause
