@echo off
cd /d %~dp0
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  py -3 duo_scanner.py --config config.json
) else (
  python duo_scanner.py --config config.json
)
pause
