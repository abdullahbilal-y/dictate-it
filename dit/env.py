"""Secrets loading. The OpenRouter key lives in the environment or a git-ignored .env, never config.json."""
import os

def load_dotenv(path: str) -> None:
    """Minimal .env loader (KEY=VALUE lines). Never overrides variables that are already set."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[7:]
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value

def get_secret(name: str) -> str:
    """Process env first, then the persisted per-user env (so `setx` works without restarting the shell)."""
    value = os.environ.get(name, "").strip()
    if value:
        return value
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value).strip()
    except OSError:
        return ""
