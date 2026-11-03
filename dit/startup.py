import os
import sys
import shutil
import subprocess

def get_startup_dir() -> str:
    return os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")

def get_startup_lnk_path() -> str:
    return os.path.join(get_startup_dir(), "DictateIt.lnk")

def is_startup_enabled() -> bool:
    return os.path.exists(get_startup_lnk_path())

def get_pythonw_path() -> str:
    # 1. Check directory of current python.exe
    py_dir = os.path.dirname(sys.executable)
    candidate = os.path.join(py_dir, "pythonw.exe")
    if os.path.exists(candidate):
        return candidate
    # 2. Check system PATH
    which_pyw = shutil.which("pythonw.exe")
    if which_pyw and os.path.exists(which_pyw):
        return which_pyw
    # Fallback to sys.executable
    return sys.executable

def enable_startup() -> bool:
    try:
        startup_dir = get_startup_dir()
        if not os.path.exists(startup_dir):
            os.makedirs(startup_dir, exist_ok=True)

        # Remove any legacy shortcuts (e.g. Dit.lnk or old DictateIt.lnk)
        for old_name in ["Dit.lnk", "DictateIt.lnk"]:
            old_file = os.path.join(startup_dir, old_name)
            if os.path.exists(old_file):
                try:
                    os.remove(old_file)
                except Exception:
                    pass

        project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        pythonw_path = get_pythonw_path()
        lnk_path = get_startup_lnk_path()

        # Build shortcut pointing directly to pythonw.exe main.py (no VBScript dependency!)
        ps_cmd = (
            f"$sh = New-Object -ComObject WScript.Shell; "
            f"$lnk = $sh.CreateShortcut('{lnk_path}'); "
            f"$lnk.TargetPath = '{pythonw_path}'; "
            f"$lnk.Arguments = 'main.py'; "
            f"$lnk.WorkingDirectory = '{project_dir}'; "
            f"$lnk.WindowStyle = 7; "
            f"$lnk.Description = 'DictateIt - Voice Dictation'; "
            f"$lnk.Save()"
        )
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], check=True, creationflags=flags)
        print(f"[Startup] Successfully registered DictateIt in Windows Startup: {lnk_path}")
        return True
    except Exception as e:
        print(f"[Startup] Failed to create startup shortcut: {e}")
        return False

def disable_startup() -> bool:
    try:
        startup_dir = get_startup_dir()
        for name in ["DictateIt.lnk", "Dit.lnk"]:
            target = os.path.join(startup_dir, name)
            if os.path.exists(target):
                try:
                    os.remove(target)
                    print(f"[Startup] Removed startup shortcut: {target}")
                except Exception:
                    pass
        return True
    except Exception as e:
        print(f"[Startup] Failed to remove startup shortcut: {e}")
        return False
