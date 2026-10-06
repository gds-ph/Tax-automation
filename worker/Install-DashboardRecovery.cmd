@echo off
echo Install with both parent and child PAD flows stopped.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-DashboardRecovery.ps1"
if errorlevel 1 echo Installation failed. Keep the worker stopped and report the error above.
pause
