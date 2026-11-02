import os
import subprocess

def get_startup_lnk_path() -> str:
    appdata = os.environ.get("APPDATA", "")
    return os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs\Startup", "Dit.lnk")

def is_startup_enabled() -> bool:
    return os.path.exists(get_startup_lnk_path())

def enable_startup() -> bool:
    try:
        project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        vbs_path = os.path.join(project_dir, "run_silent_tray.vbs")
        lnk_path = get_startup_lnk_path()

        # Create shortcut using Windows Script Host via PowerShell
        ps_cmd = (
            f"$ws = New-Object -ComObject WScript.Shell; "
            f"$s = $ws.CreateShortcut('{lnk_path}'); "
            f"$s.TargetPath = 'wscript.exe'; "
            f"$s.Arguments = '`\"{vbs_path}`\"'; "
            f"$s.WorkingDirectory = '{project_dir}'; "
            f"$s.WindowStyle = 7; "
            f"$s.Description = 'D^it - Dictate It'; "
            f"$s.Save()"
        )
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], check=True, creationflags=flags)
        print(f"[Startup] Successfully added D^it shortcut to: {lnk_path}")
        return True
    except Exception as e:
        print(f"[Startup] Failed to create startup shortcut: {e}")
        return False

def disable_startup() -> bool:
    try:
        lnk_path = get_startup_lnk_path()
        if os.path.exists(lnk_path):
            os.remove(lnk_path)
            print(f"[Startup] Removed D^it startup shortcut: {lnk_path}")
        return True
    except Exception as e:
        print(f"[Startup] Failed to remove startup shortcut: {e}")
        return False
