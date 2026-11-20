"""Makes DictateIt a proper Windows app: its own DictateIt.exe (logo icon, "DictateIt" in Task Manager and
Startup apps), a Start Menu entry, and a logon task for startup.

DictateIt.exe is a copy of pythonw.exe with its icon and version info replaced, plus the Python runtime DLLs and
a pyvenv.cfg pointing at the installed Python, so it runs the same interpreter and packages. (pythonw.exe's own
description is "Python", which is all Task Manager could show before.) Built into <project>/bin, git-ignored.

Startup uses a Task Scheduler logon task instead of the Startup folder: Windows launched Startup-folder items
minutes after login, or not at all before a quick restart (landmine #22)."""
import io
import os
import shutil
import struct
import subprocess
import sys
import tempfile

from PIL import Image

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_DIR = os.path.join(PROJECT_DIR, "bin")
EXE = os.path.join(BIN_DIR, "DictateIt.exe")
CONSOLE_EXE = os.path.join(BIN_DIR, "DictateIt-console.exe")
ICO = os.path.join(BIN_DIR, "DictateIt.ico")
TASK_NAME = "DictateIt"
VERSION = (1, 2, 0, 0)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

RT_ICON, RT_GROUP_ICON, RT_VERSION = 3, 14, 16


def start_menu_lnk() -> str:
    return os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\DictateIt.lnk")


def legacy_startup_lnks():
    folder = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")
    return [os.path.join(folder, n) for n in ("DictateIt.lnk", "Dit.lnk")]


# ------------------------------------------------------------------ icon
def _logo_images():
    from .ui.lottie import render_logo
    sizes = [256, 64, 48, 32, 24, 16]
    big = render_logo(os.path.join(PROJECT_DIR, "assets", "animations"), 256, dark=False)
    if big is None:
        return None
    return [big if s == 256 else big.resize((s, s), Image.LANCZOS) for s in sizes]


def build_icon() -> bool:
    images = _logo_images()
    if not images:
        print("[Install] No assets/animations/logo.json: keeping the default icon.")
        return False
    images[0].save(ICO, format="ICO", sizes=[(i.width, i.height) for i in images])
    return True


def _icon_resources(ico_path):
    """Split an .ico file into (GRPICONDIR bytes, [(id, image bytes)]) for exe resources."""
    data = open(ico_path, "rb").read()
    _, _, count = struct.unpack_from("<HHH", data, 0)
    entries, images = [], []
    for i in range(count):
        w, h, colors, _, planes, bpp, size, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
        icon_id = i + 1
        images.append((icon_id, data[offset:offset + size]))
        entries.append(struct.pack("<BBBBHHIH", w, h, colors, 0, planes, bpp, size, icon_id))
    return struct.pack("<HHH", 0, 1, count) + b"".join(entries), images


# ------------------------------------------------------------------ version info
def _vs_block(key, value=b"", children=(), wtype=1, value_len=None):
    key_b = (key + "\0").encode("utf-16-le")
    head = 6 + len(key_b)
    body = key_b + b"\0" * ((4 - head % 4) % 4) + value
    kids = b""
    for child in children:
        kids += b"\0" * ((4 - (len(body) + 6 + len(kids)) % 4) % 4) + child
    body += kids
    vlen = len(value) if value_len is None else value_len
    return struct.pack("<HHH", 6 + len(body), vlen, wtype) + body


def _version_resource():
    ms = (VERSION[0] << 16) | VERSION[1]
    ls = (VERSION[2] << 16) | VERSION[3]
    fixed = struct.pack("<13I", 0xFEEF04BD, 0x00010000, ms, ls, ms, ls, 0x3F, 0, 0x40004, 1, 0, 0, 0)
    ver = ".".join(map(str, VERSION))
    strings = {
        "CompanyName": "DictateIt", "FileDescription": "DictateIt", "FileVersion": ver,
        "InternalName": "DictateIt", "LegalCopyright": "MIT License", "OriginalFilename": "DictateIt.exe",
        "ProductName": "DictateIt", "ProductVersion": ver,
    }
    string_blocks = [_vs_block(k, (v + "\0").encode("utf-16-le"), wtype=1, value_len=len(v) + 1)
                     for k, v in strings.items()]
    table = _vs_block("040904B0", children=string_blocks)
    sfi = _vs_block("StringFileInfo", children=[table])
    var = _vs_block("Translation", struct.pack("<HH", 0x0409, 0x04B0), wtype=0)
    vfi = _vs_block("VarFileInfo", children=[var])
    return _vs_block("VS_VERSION_INFO", fixed, children=[sfi, vfi], wtype=0)


def _rebrand(exe_path, with_icon):
    import win32api
    h = win32api.BeginUpdateResource(exe_path, False)
    try:
        win32api.UpdateResource(h, RT_VERSION, 1, _version_resource(), 1033)
        if with_icon:
            group, images = _icon_resources(ICO)
            for icon_id, blob in images:
                win32api.UpdateResource(h, RT_ICON, icon_id, blob, 1033)
            win32api.UpdateResource(h, RT_GROUP_ICON, 1, group, 1033)
    finally:
        win32api.EndUpdateResource(h, False)


# ------------------------------------------------------------------ build
def build_launcher(force: bool = False) -> str:
    base = os.path.dirname(sys.executable)
    if os.path.basename(sys.executable).lower().startswith("dictateit"):
        base = _home_from_cfg() or base
    if os.path.exists(EXE) and not force:
        return EXE
    os.makedirs(BIN_DIR, exist_ok=True)
    for dll in ("python3.dll", f"python{sys.version_info[0]}{sys.version_info[1]}.dll",
                "vcruntime140.dll", "vcruntime140_1.dll"):
        src = os.path.join(base, dll)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(BIN_DIR, dll))
    with open(os.path.join(BIN_DIR, "pyvenv.cfg"), "w", encoding="utf-8") as f:
        f.write(f"home = {base}\ninclude-system-site-packages = true\n"
                f"version = {sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}\n")
    with_icon = build_icon()
    for src_name, dst in (("pythonw.exe", EXE), ("python.exe", CONSOLE_EXE)):
        shutil.copy2(os.path.join(base, src_name), dst)
        _rebrand(dst, with_icon)
    print(f"[Install] Built {EXE}")
    return EXE


def _home_from_cfg():
    try:
        for line in open(os.path.join(BIN_DIR, "pyvenv.cfg"), encoding="utf-8"):
            if line.startswith("home"):
                return line.split("=", 1)[1].strip()
    except OSError:
        return None


def launcher_works() -> bool:
    """Run the console twin to prove the copied runtime finds the stdlib and installed packages."""
    try:
        out = subprocess.run([CONSOLE_EXE, "-c", "import faster_whisper, pystray, PIL; print('ok')"],
                             capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW)
        if out.stdout.strip().endswith("ok"):
            return True
        print(f"[Install] Launcher check failed: {out.stderr.strip()[-300:]}")
    except (OSError, subprocess.SubprocessError) as e:
        print(f"[Install] Launcher check failed: {e}")
    return False


def launch_command():
    """(exe, args) used by shortcuts and the logon task. Falls back to pythonw if the launcher can't run."""
    if os.path.exists(EXE):
        return EXE, "main.py"
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return (pythonw if os.path.exists(pythonw) else sys.executable), "main.py"


# ------------------------------------------------------------------ shortcuts + startup task
def _ps(script: str):
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, creationflags=NO_WINDOW)


def create_start_menu_shortcut() -> str:
    exe, args = launch_command()
    lnk = start_menu_lnk()
    icon = ICO if os.path.exists(ICO) else exe
    _ps(f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
        f"$s.TargetPath='{exe}';$s.Arguments='{args}';$s.WorkingDirectory='{PROJECT_DIR}';"
        f"$s.IconLocation='{icon},0';$s.Description='DictateIt - voice dictation and tasks';$s.Save()")
    print(f"[Install] Start Menu entry: {lnk}")
    return lnk


def _task_xml(exe, args):
    user = os.environ.get("USERDOMAIN", "") + "\\" + os.environ.get("USERNAME", "")
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Starts DictateIt (voice dictation and tasks) when you sign in.</Description></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{esc(user)}</UserId><Delay>PT5S</Delay></LogonTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>{esc(user)}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure><Interval>PT1M</Interval><Count>3</Count></RestartOnFailure>
    <Priority>5</Priority>
  </Settings>
  <Actions Context="Author"><Exec><Command>{esc(exe)}</Command><Arguments>{esc(args)}</Arguments><WorkingDirectory>{esc(PROJECT_DIR)}</WorkingDirectory></Exec></Actions>
</Task>"""


def enable_startup() -> bool:
    exe, args = launch_command()
    path = os.path.join(tempfile.mkdtemp(prefix="dictateit-task-"), "task.xml")
    with open(path, "w", encoding="utf-16") as f:
        f.write(_task_xml(exe, args))
    r = subprocess.run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", path, "/F"], capture_output=True,
                       text=True, creationflags=NO_WINDOW)
    if r.returncode != 0:
        print(f"[Startup] Could not create the logon task: {(r.stderr or r.stdout).strip()}")
        return False
    for old in legacy_startup_lnks():   # one start mechanism only
        if os.path.exists(old):
            os.remove(old)
    _startup_cache.clear()
    print(f"[Startup] DictateIt starts at sign-in (Task Scheduler task '{TASK_NAME}', 5s after logon).")
    return True


def disable_startup() -> bool:
    subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True, creationflags=NO_WINDOW)
    for old in legacy_startup_lnks():
        if os.path.exists(old):
            os.remove(old)
    _startup_cache.clear()
    print("[Startup] Removed DictateIt from startup.")
    return True


_startup_cache = {}


def is_startup_enabled() -> bool:
    import time
    hit = _startup_cache.get("v")
    if hit and time.time() - hit[1] < 5:
        return hit[0]
    r = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME], capture_output=True, creationflags=NO_WINDOW)
    value = r.returncode == 0 or any(os.path.exists(p) for p in legacy_startup_lnks())
    _startup_cache["v"] = (value, time.time())
    return value


def install() -> bool:
    build_launcher(force=True)
    ok = launcher_works()
    if not ok:
        print("[Install] Branded launcher couldn't load Python; shortcuts will use pythonw.exe instead.")
        for f in (EXE, CONSOLE_EXE):
            if os.path.exists(f):
                os.remove(f)
    create_start_menu_shortcut()
    enable_startup()
    return ok
