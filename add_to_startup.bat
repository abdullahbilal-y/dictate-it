@echo off
cd /d "%~dp0"
echo Installing DictateIt: app launcher, Start Menu entry, start at sign-in...
python main.py --install
pause
