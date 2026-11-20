"""Window title -> Context: which app, what you're on, and (for editors) which workspace/repo."""
import os
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

from .browser import site_of
from .window import WindowInfo

APP_NAMES = {
    "chrome.exe": "Chrome", "msedge.exe": "Edge", "firefox.exe": "Firefox", "brave.exe": "Brave",
    "opera.exe": "Opera", "vivaldi.exe": "Vivaldi", "arc.exe": "Arc",
    "code.exe": "VS Code", "code - insiders.exe": "VS Code", "cursor.exe": "Cursor", "windsurf.exe": "Windsurf",
    "devenv.exe": "Visual Studio", "pycharm64.exe": "PyCharm", "idea64.exe": "IntelliJ", "rider64.exe": "Rider",
    "excel.exe": "Excel", "winword.exe": "Word", "powerpnt.exe": "PowerPoint", "onenote.exe": "OneNote",
    "outlook.exe": "Outlook", "olk.exe": "Outlook", "teams.exe": "Teams", "ms-teams.exe": "Teams",
    "slack.exe": "Slack", "discord.exe": "Discord", "notion.exe": "Notion", "obsidian.exe": "Obsidian",
    "figma.exe": "Figma", "explorer.exe": "File Explorer", "windowsterminal.exe": "Terminal",
    "notepad.exe": "Notepad", "notepad++.exe": "Notepad++", "acrobat.exe": "Acrobat", "robloxstudiobeta.exe": "Roblox Studio",
}
BROWSERS = {"Chrome", "Edge", "Firefox", "Brave", "Opera", "Vivaldi", "Arc"}
EDITORS = {"VS Code", "Cursor", "Windsurf"}
PRIVATE_MARKERS = ("incognito", "inprivate", "private browsing")
SEPARATOR = re.compile(r"\s+[-–—|]\s+")


@dataclass
class Context:
    app: str
    exe: str
    label: str                 # human-readable "what you're on", app name stripped
    workspace: Optional[str]   # editor folder / repo, when known
    branch: Optional[str]
    key: str                   # stable identity used for linking
    private: bool = False
    url: Optional[str] = None  # browsers: active tab, scheme://host/path (no query/fragment)
    site: Optional[str] = None # browsers: host without www.

    def describe(self) -> str:
        if self.workspace and self.workspace not in self.label:
            return f"{self.label} · {self.workspace}"
        if self.site and self.site.split(".")[0] not in self.label.lower():
            return f"{self.label} · {self.site}"
        return self.label


def app_name(exe: str) -> str:
    if exe in APP_NAMES:
        return APP_NAMES[exe]
    stem = os.path.splitext(exe)[0]
    return stem[:1].upper() + stem[1:] if stem else "App"


def _is_app_segment(segment: str, app: str, exe: str) -> bool:
    seg = segment.lower().replace("​", "")
    stem = os.path.splitext(exe)[0].lower()
    return (app.lower() in seg or (stem and stem in seg) or seg in ("google chrome", "mozilla firefox",
            "microsoft edge", "visual studio code"))


_branch_cache = {}


def git_branch(path: str) -> Optional[str]:
    cached = _branch_cache.get(path)
    if cached and time.time() - cached[1] < 60:
        return cached[0]
    branch = None
    try:
        out = subprocess.run(["git", "-C", path, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True,
                             text=True, timeout=2, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if out.returncode == 0:
            branch = out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        branch = None
    _branch_cache[path] = (branch, time.time())
    return branch


def clean_tab_title(name: str) -> str:
    """Tab-strip names carry extras: "Page - Memory usage - 120 MB", "Page, playing audio", "(3) Inbox"."""
    name = re.sub(r"\s+-\s+(memory usage|high memory usage).*$", "", name, flags=re.I)
    name = re.sub(r",?\s*(playing audio|audio muted|sleeping tab|pinned)\b.*$", "", name, flags=re.I)
    name = re.sub(r"^\(\d+\+?\)\s*", "", name).strip()
    # Untitled pages show their address as the tab name, query string and all (login tokens, emails, search
    # terms). Treat it like any other URL: keep host + path only (landmine #21).
    if name and " " not in name and ("/" in name or "?" in name or "://" in name):
        from .browser import clean_url
        cleaned = clean_url(name)
        return cleaned.split("://", 1)[1] if cleaned else ""
    return name


def build_context(win: WindowInfo, private_apps=(), url: Optional[str] = None,
                  tab_title: Optional[str] = None) -> Context:
    app = app_name(win.exe)
    title = win.title.replace("​", "").strip()

    if win.exe in private_apps or any(m in title.lower() for m in PRIVATE_MARKERS):
        return Context(app=app, exe=win.exe, label="Private window", workspace=None, branch=None,
                       key=f"{app}::private".lower(), private=True)

    title = re.sub(r"^\(\d+\+?\)\s*", "", title)          # "(3) Inbox" notification counts
    title = re.sub(r"^[●•*]\s*", "", title)               # unsaved-file markers
    title = re.sub(r"\s+and \d+ more pages?", "", title)  # Edge tab groups
    parts = [p.strip() for p in SEPARATOR.split(title) if p.strip()]
    while len(parts) > 1 and _is_app_segment(parts[-1], app, win.exe):
        parts.pop()
    if app == "Edge" and len(parts) > 1 and re.fullmatch(r"(personal|work|profile \d+)", parts[-1].lower()):
        parts.pop()

    workspace, branch = None, None
    if app in EDITORS and len(parts) >= 2:
        workspace = re.sub(r"\s*\((workspace|wsl.*|ssh.*)\)$", "", parts[-1], flags=re.I).strip()
        # VS Code's `window.title` can be set to show the full folder path; then we can read the git branch.
        if os.path.isabs(workspace) and os.path.isdir(workspace):
            branch = git_branch(workspace)
            workspace = os.path.basename(workspace.rstrip("\\/")) or workspace
    label = " - ".join(parts) if parts else app
    if app in BROWSERS and tab_title:
        # The tab's own title beats the window title (Edge Workspaces show only the workspace name there).
        label = clean_tab_title(tab_title) or label

    site = site_of(url) if app in BROWSERS else None
    url = url if site else None
    # Browsers: the page address is a steadier identity than its title (titles change with unread counts,
    # edits, notifications). Editors: the workspace, so switching files inside a repo stays one context.
    if url:
        identity = url.split("://", 1)[1].removeprefix("www.")
    else:
        identity = workspace if workspace else label
    key = re.sub(r"\s+", " ", f"{app}::{identity}".lower())[:200]
    return Context(app=app, exe=win.exe, label=label[:200], workspace=workspace, branch=branch, key=key,
                   url=url, site=site)
