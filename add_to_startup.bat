@echo off
title D^it - Add to Windows Startup
cd /d "%~dp0"
python -c "from dit.startup import enable_startup; enable_startup()"
echo.
echo =======================================================
echo  D^it has been added to your Windows Startup apps!
echo  It will now launch automatically in the System Tray
echo  every time you log in to your computer.
echo =======================================================
echo.
pause
