@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 San_Andreas_Audio_Toolbox_PC_PS2_GUI.py
) else (
  python San_Andreas_Audio_Toolbox_PC_PS2_GUI.py
)
if errorlevel 1 pause
