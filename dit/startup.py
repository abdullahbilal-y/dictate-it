"""Start-with-Windows. Delegates to dit.launcher (Task Scheduler logon task + branded DictateIt.exe).

Kept as a module so the tray, CLI flags and .bat scripts keep importing the same names."""
from .launcher import enable_startup, disable_startup, is_startup_enabled  # noqa: F401
