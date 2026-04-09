"""Environment-only API configuration (no hardcoded keys or archive fallbacks)."""

import os
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent
_DOTENV_PATH = _REPO_ROOT / ".env"


def load_dotenv(path: Optional[Path] = None, *, override: bool = False) -> None:
    """Load KEY=value pairs from a .env file into os.environ (existing vars win unless override)."""
    env_path = path or _DOTENV_PATH
    if not env_path.is_file():
        return
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, rest = line.partition("=")
        key = key.strip()
        if not key:
            continue
        val = rest.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if override or key not in os.environ:
            os.environ[key] = val


load_dotenv()


def get_openai_api_key() -> str:
    return (os.environ.get("OPENAI_API_KEY") or "").strip()


def resolve_openai_api_key(explicit: Optional[str] = None) -> str:
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    return get_openai_api_key()


def get_opensubtitles_api_key() -> str:
    return (os.environ.get("OPENSUBTITLES_API_KEY") or "").strip()


def get_tmdb_api_key() -> str:
    """The Movie Database (TMDB) v3 API key — used for trending/popular TV lists."""
    return (os.environ.get("TMDB_API_KEY") or "").strip()
