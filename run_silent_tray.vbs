' Launch D^it silently into the Windows System Tray without a terminal window
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "pythonw.exe main.py", 0, False

