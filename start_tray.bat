@echo off
cd /d "%~dp0"
if exist "bin\DictateIt.exe" (start "" "bin\DictateIt.exe" main.py) else (start "" pythonw.exe main.py)
exit
