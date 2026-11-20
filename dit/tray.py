import os
import threading
import time
from PIL import Image, ImageDraw
import pystray
from .config import save_config
from .startup import is_startup_enabled, enable_startup, disable_startup

def create_circle_icon(color: tuple, accent_symbol: str = "mic"):
    width, height = 64, 64
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Outer circle
    draw.ellipse([4, 4, 60, 60], fill=color)

    if accent_symbol == "mic":
        # White microphone shape
        draw.rounded_rectangle([25, 14, 39, 36], radius=7, fill=(255, 255, 255))
        draw.arc([19, 22, 45, 42], start=0, end=180, fill=(255, 255, 255), width=3)
        draw.line([32, 42, 32, 50], fill=(255, 255, 255), width=3)
        draw.line([24, 50, 40, 50], fill=(255, 255, 255), width=3)
    elif accent_symbol == "rec":
        # Recording inner circle
        draw.ellipse([18, 18, 46, 46], fill=(255, 255, 255))
    elif accent_symbol == "busy":
        # Transcribing star/lightning
        draw.polygon([(32, 12), (24, 32), (32, 32), (28, 52), (40, 28), (32, 28)], fill=(255, 255, 255))

    return image

HOTKEY_PRESETS = [
    ("Ctrl + Alt + D (Recommended - Conflict Free)", "ctrl+alt+d"),
    ("Ctrl + Alt + Space (Thumb Friendly)", "ctrl+alt+space"),
    ("F8 (Single Key)", "f8"),
    ("Alt + \\ (Symbol Key)", "alt+\\"),
    ("Ctrl + Shift + D (Legacy)", "ctrl+shift+d"),
]

STATUS_DOTS = {"active": "▶", "paused": "⏸", "ready": "•", "waiting": "⏳"}

def taskbar_is_light() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return bool(winreg.QueryValueEx(key, "SystemUsesLightTheme")[0])
    except OSError:
        return False


def logo_icons(animations_dir: str):
    """(idle, recording, busy) tray icons from assets/animations/logo.json, or None to use the drawn ones.
    Recording/busy add a status dot in the corner so the logo stays recognisable."""
    from .ui.lottie import render_logo
    logo = render_logo(animations_dir, 64, dark=not taskbar_is_light())
    if logo is None:
        return None

    def with_dot(color):
        img = logo.copy()
        draw = ImageDraw.Draw(img)
        draw.ellipse([38, 38, 63, 63], fill=(0, 0, 0, 0))          # cut a gap so the dot reads on any logo colour
        img.putalpha(Image.composite(Image.new("L", img.size, 0), img.getchannel("A"),
                                     _dot_mask(img.size, (38, 38, 63, 63))))
        draw = ImageDraw.Draw(img)
        draw.ellipse([42, 42, 61, 61], fill=color)
        return img

    return logo, with_dot((231, 76, 60, 255)), with_dot((243, 156, 18, 255))


def _dot_mask(size, box):
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).ellipse(box, fill=255)
    return mask


class SystemTrayApp:
    def __init__(self, engine, config, tasks=None, watcher=None, ai=None):
        self.engine = engine
        self.config = config
        self.tasks = tasks        # TaskManager or None
        self.watcher = watcher    # ContextWatcher or None
        self.ai = ai              # OpenRouterClient or None
        if self.tasks:
            self.tasks.add_listener(self._refresh_menu)
        
        self.icon_idle = create_circle_icon((41, 128, 185), "mic")       # Blue
        self.icon_rec = create_circle_icon((231, 76, 60), "rec")         # Red
        self.icon_busy = create_circle_icon((243, 156, 18), "busy")      # Orange
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        branded = logo_icons(os.path.join(project_dir, config.animations_dir))
        if branded:
            self.icon_idle, self.icon_rec, self.icon_busy = branded

        self.tray = None
        self._thread = None
        self.status_text = f"Ready ({self.config.hotkey.upper()})"

    def _build_menu(self):
        def _toggle_dictation(icon, item):
            if self.engine.is_listening:
                self.engine.stop_dictation()
            else:
                self.engine.start_dictation()

        def _set_mode(mode_val):
            def handler(icon, item):
                self.config.mode = mode_val
                if self.engine.listener:
                    self.engine.listener.mode = mode_val   # read on every key event
                save_config(self.config)
                self._refresh_menu()
            return handler

        def _set_hotkey(hotkey_val):
            def handler(icon, item):
                self.config.hotkey = hotkey_val
                if self.engine.listener:
                    self.engine.listener.update_hotkey(hotkey_val)
                save_config(self.config)
                self.set_idle()
                self._refresh_menu()
            return handler

        def _toggle_cues(icon, item):
            self.config.audio_cues = not self.config.audio_cues
            self.engine.feedback.enabled = self.config.audio_cues
            save_config(self.config)
            self._refresh_menu()

        def _toggle_startup(icon, item):
            if is_startup_enabled():
                disable_startup()
            else:
                enable_startup()
            self._refresh_menu()

        def _quit_app(icon, item):
            if self.engine.listener:
                self.engine.listener.stop()
            self.tray.stop()

        def _toggle_watcher(icon, item):
            if self.watcher:
                self.watcher.set_paused(not self.watcher.paused)
            self._refresh_menu()

        def _toggle_ai(icon, item):
            if self.ai:
                self.ai.enabled = not self.ai.enabled
            self._refresh_menu()

        # Build Hotkey Submenu
        hotkey_menu_items = [
            pystray.MenuItem(
                label,
                _set_hotkey(key_code),
                checked=lambda item, kc=key_code: self.config.hotkey.lower() == kc.lower()
            )
            for label, key_code in HOTKEY_PRESETS
        ]
        hotkey_submenu = pystray.Menu(*hotkey_menu_items)

        menu_items = [
            pystray.MenuItem("DictateIt", None, enabled=False),
            pystray.MenuItem(lambda text: f"Status: {self.status_text}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda text: f"🎙️ Start / Stop Dictation ({self.config.hotkey.upper()})",
                _toggle_dictation,
                default=True
            ),
        ]
        if self.tasks:
            menu_items += self._task_menu_items()
        menu_items += [
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Shortcut Key", hotkey_submenu),
            pystray.MenuItem(
                "Mode: Toggle (Press to start/stop)",
                _set_mode("toggle"),
                checked=lambda item: self.config.mode == "toggle"
            ),
            pystray.MenuItem(
                "Mode: Push-to-Talk (Hold while speaking)",
                _set_mode("ptt"),
                checked=lambda item: self.config.mode == "ptt"
            ),
            pystray.MenuItem(
                "Sound Cues",
                _toggle_cues,
                checked=lambda item: self.config.audio_cues
            ),
            pystray.MenuItem(
                "Start with Windows",
                _toggle_startup,
                checked=lambda item: is_startup_enabled()
            ),
        ]
        if self.tasks:
            from .ui.paper import THEMES

            def _set_look(style, palette=None):
                def handler(icon, item):
                    self.config.card_style = style
                    self.tasks.ui.style = style   # applies from the next card
                    if palette:
                        self.config.paper_theme = palette
                        self.tasks.ui.palette = palette
                    save_config(self.config)
                    self._refresh_menu()
                    self.tasks.greet()            # preview the new look right away
                return handler
            looks = [pystray.MenuItem(
                f"Mechanical: {theme['label']}", _set_look("paper", name),
                checked=lambda item, n=name: self.config.card_style == "paper" and self.config.paper_theme == n)
                for name, theme in THEMES.items()]
            looks.append(pystray.MenuItem("Glass (frosted, follows Windows theme)", _set_look("glass"),
                                          checked=lambda item: self.config.card_style == "glass"))
            menu_items.append(pystray.MenuItem("Look", pystray.Menu(*looks)))
        if getattr(self.engine, "cloud_stt", None):
            def _toggle_route(route):
                def handler(icon, item):
                    routes = list(self.config.stt_cloud_routes or [])
                    if route in routes:
                        routes.remove(route)
                    else:
                        routes.append(route)
                    self.config.stt_cloud_routes = routes
                    save_config(self.config)
                    self._refresh_menu()
                return handler
            menu_items.append(pystray.MenuItem(
                "Groq speech for task commands", _toggle_route("task"),
                checked=lambda item: "task" in (self.config.stt_cloud_routes or [])))
            menu_items.append(pystray.MenuItem(
                "Groq speech for dictation (audio leaves PC)", _toggle_route("dictate"),
                checked=lambda item: "dictate" in (self.config.stt_cloud_routes or [])))
        if self.watcher:
            menu_items.append(pystray.MenuItem(
                "Watch app context (titles only)", _toggle_watcher,
                checked=lambda item: not self.watcher.paused))
        if self.ai:
            menu_items.append(pystray.MenuItem(
                lambda text: self.ai.status_text(), _toggle_ai,
                checked=lambda item: self.ai.enabled and bool(self.ai.api_key),
                enabled=bool(self.ai.api_key)))
        menu_items += [
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit DictateIt", _quit_app)
        ]
        return pystray.Menu(*menu_items)

    def _task_menu_items(self):
        from .tasks.models import ACTIVE, PAUSED, WAITING, COMPLETED, REMOVED

        def _record_task(icon, item):
            if self.engine.is_listening:
                self.engine.stop_dictation()
            else:
                self.engine.start_dictation("task")

        def _set(task_id, status):
            def handler(icon, item):
                threading.Thread(target=self.tasks.set_status, args=(task_id, status),
                                 kwargs={"via": "tray"}, daemon=True).start()
            return handler

        def _open(task_id):
            def handler(icon, item):
                self.tasks.open_task(task_id)
            return handler

        try:
            open_tasks = self.tasks.store.open_tasks()
        except Exception as e:
            print(f"[Tray] Could not read tasks: {e}")
            open_tasks = []

        task_items = []
        for t in open_tasks[:12]:
            label = f"{STATUS_DOTS.get(t.status, '•')}  {t.title[:48]}"
            task_items.append(pystray.MenuItem(label, pystray.Menu(
                pystray.MenuItem("Start working on it", _set(t.id, ACTIVE), enabled=t.status != ACTIVE),
                pystray.MenuItem("Mark done", _set(t.id, COMPLETED)),
                pystray.MenuItem("Pause", _set(t.id, PAUSED), enabled=t.status != PAUSED),
                pystray.MenuItem("Waiting on someone", _set(t.id, WAITING), enabled=t.status != WAITING),
                pystray.MenuItem("Remove", _set(t.id, REMOVED)),
                pystray.MenuItem("Reopen last page", _open(t.id), visible=bool(t.last_url)),
            )))
        if not task_items:
            task_items.append(pystray.MenuItem("No open tasks", None, enabled=False))

        return [
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f"✚ Add Task by Voice ({self.config.task_hotkey.upper()})", _record_task),
            pystray.MenuItem(f"Show Queue ({self.config.peek_hotkey.upper()})",
                             lambda icon, item: self.tasks.show_peek()),
            pystray.MenuItem(f"Tasks ({len(open_tasks)} open)", pystray.Menu(*task_items)),
        ]

    def _refresh_menu(self):
        if self.tray:
            self.tray.menu = self._build_menu()

    def set_idle(self):
        self.status_text = f"Ready ({self.config.hotkey.upper()})"
        if self.tray:
            self.tray.icon = self.icon_idle
            self.tray.title = f"DictateIt: {self.status_text}"

    def set_recording(self):
        self.status_text = "Listening... Speak now"
        if self.tray:
            self.tray.icon = self.icon_rec
            self.tray.title = f"DictateIt: {self.status_text}"

    def set_transcribing(self):
        self.status_text = "Transcribing with Whisper..."
        if self.tray:
            self.tray.icon = self.icon_busy
            self.tray.title = f"DictateIt: {self.status_text}"

    def start(self):
        self.tray = pystray.Icon(
            "DictateItTray",
            self.icon_idle,
            f"DictateIt: {self.status_text}",
            self._build_menu()
        )
        self._thread = threading.Thread(target=self.tray.run, daemon=True)
        self._thread.start()

    def stop(self):
        if self.tray:
            self.tray.stop()
