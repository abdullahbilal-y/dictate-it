"""Reads Windows appearance settings: light/dark, high contrast, animation preference, screen reader."""
import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field

user32 = ctypes.WinDLL("user32", use_last_error=True)

SPI_GETHIGHCONTRAST = 0x0042
SPI_GETSCREENREADER = 0x0046
SPI_GETCLIENTAREAANIMATION = 0x1042
HCF_HIGHCONTRASTON = 0x00000001
COLOR_WINDOW, COLOR_WINDOWTEXT, COLOR_HIGHLIGHT, COLOR_GRAYTEXT, COLOR_HOTLIGHT = 5, 8, 13, 17, 26


class HIGHCONTRASTW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwFlags", wintypes.DWORD), ("lpszDefaultScheme", wintypes.LPWSTR)]


def _hex(value: str, alpha: int = 255):
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha)


def _sys_color(index: int, alpha: int = 255):
    c = user32.GetSysColor(index)
    return (c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF, alpha)


@dataclass
class Theme:
    name: str
    surface: tuple            # card body
    border: tuple
    sheen: tuple              # top highlight gradient start
    text: tuple
    muted: tuple
    faint: tuple              # separators, inactive bars
    button: tuple
    button_hover: tuple
    shadow_alpha: int
    accents: dict = field(default_factory=dict)
    high_contrast: bool = False
    reduce_motion: bool = False
    screen_reader: bool = False
    border_width: int = 1

    def accent(self, kind: str):
        return self.accents.get(kind, self.accents["queued"])


DARK_ACCENTS = {
    "queued": "A78BFA", "listening": "A78BFA", "thinking": "A78BFA", "active": "38BDF8", "resume": "38BDF8",
    "done": "4ADE80", "removed": "FB7185", "paused": "FBBF24", "nudge": "FBBF24", "waiting": "94A3B8",
    "info": "94A3B8", "peek": "A78BFA",
}
LIGHT_ACCENTS = {
    "queued": "7C3AED", "listening": "7C3AED", "thinking": "7C3AED", "active": "0284C7", "resume": "0284C7",
    "done": "16A34A", "removed": "E11D48", "paused": "D97706", "nudge": "D97706", "waiting": "64748B",
    "info": "64748B", "peek": "7C3AED",
}


def _apps_use_light_theme() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return bool(winreg.QueryValueEx(key, "AppsUseLightTheme")[0])
    except OSError:
        return False


def _spi_bool(action: int) -> bool:
    value = wintypes.BOOL(False)
    if not user32.SystemParametersInfoW(action, 0, ctypes.byref(value), 0):
        return False
    return bool(value.value)


def high_contrast_on() -> bool:
    hc = HIGHCONTRASTW(cbSize=ctypes.sizeof(HIGHCONTRASTW))
    if not user32.SystemParametersInfoW(SPI_GETHIGHCONTRAST, hc.cbSize, ctypes.byref(hc), 0):
        return False
    return bool(hc.dwFlags & HCF_HIGHCONTRASTON)


def animations_enabled() -> bool:
    value = wintypes.BOOL(True)
    if not user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(value), 0):
        return True
    return bool(value.value)


def detect_theme() -> Theme:
    reduce_motion = not animations_enabled()
    screen_reader = _spi_bool(SPI_GETSCREENREADER)

    if high_contrast_on():
        bg, fg = _sys_color(COLOR_WINDOW), _sys_color(COLOR_WINDOWTEXT)
        hi, gray = _sys_color(COLOR_HIGHLIGHT), _sys_color(COLOR_GRAYTEXT)
        return Theme(name="contrast", surface=bg, border=fg, sheen=(0, 0, 0, 0), text=fg, muted=fg, faint=gray,
                     button=bg, button_hover=hi, shadow_alpha=0, accents={k: hi for k in DARK_ACCENTS},
                     high_contrast=True, reduce_motion=reduce_motion, screen_reader=screen_reader, border_width=2)

    if _apps_use_light_theme():
        return Theme(name="light", surface=_hex("FBFBFD", 246), border=(0, 0, 0, 22), sheen=(255, 255, 255, 120),
                     text=_hex("16161A"), muted=_hex("5F5F6B"), faint=(0, 0, 0, 26), button=(0, 0, 0, 12),
                     button_hover=(0, 0, 0, 24), shadow_alpha=60,
                     accents={k: _hex(v) for k, v in LIGHT_ACCENTS.items()},
                     reduce_motion=reduce_motion, screen_reader=screen_reader)

    return Theme(name="dark", surface=_hex("1B1B22", 242), border=(255, 255, 255, 22), sheen=(255, 255, 255, 14),
                 text=_hex("F4F4F6"), muted=_hex("A1A1AD"), faint=(255, 255, 255, 26), button=(255, 255, 255, 16),
                 button_hover=(255, 255, 255, 30), shadow_alpha=120,
                 accents={k: _hex(v) for k, v in DARK_ACCENTS.items()},
                 reduce_motion=reduce_motion, screen_reader=screen_reader)
