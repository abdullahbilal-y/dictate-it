@echo off
title DictateIt - Remove from Windows Startup
cd /d "%~dp0"
python -c "from dit.startup import disable_startup; disable_startup()"
echo.
echo =======================================================
echo  DictateIt has been removed from Windows Startup.
echo =======================================================
echo.
pause
