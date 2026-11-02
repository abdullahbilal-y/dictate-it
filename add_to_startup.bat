@echo off
title DictateIt - Add to Windows Startup
cd /d "%~dp0"
python -c "from dit.startup import enable_startup; enable_startup()"
echo.
echo =======================================================
echo  DictateIt has been added to your Windows Startup apps!
echo  It will launch silently in the System Tray every time
echo  you log in.
echo =======================================================
echo.
pause
