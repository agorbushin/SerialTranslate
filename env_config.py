"""Environment-only API configuration (no hardcoded keys or archive fallbacks)."""

import os
from pathlib import Path
from typing import List, Optional

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
    primary = (os.environ.get("OPENSUBTITLES_API_KEY") or "").strip()
    if primary:
        return primary
    for env_name in (
        "OPENSUBTITLES_API_KEY_2",
        "OPENSUBTITLES_API_KEY_ALT",
        "OPENSUBTITLES_API_ALTERNATIVE_KEY",
        "OPENSUBTITLES_API_KEY_FALLBACK",
        "opensubtitles_api_alternative_key",
    ):
        key = (os.environ.get(env_name) or "").strip()
        if key:
            return key
    values = _split_env_values(os.environ.get("OPENSUBTITLES_API_KEYS") or "")
    return values[0] if values else ""


def _split_env_values(value: str) -> List[str]:
    values: List[str] = []
    for part in value.replace("\n", ",").replace(";", ",").split(","):
        part = part.strip()
        if part:
            values.append(part)
    return values


def get_opensubtitles_api_keys(explicit: Optional[str] = None) -> List[str]:
    """Return OpenSubtitles API keys in fallback order, de-duplicated."""
    raw_keys: List[str] = []
    if explicit and str(explicit).strip():
        raw_keys.append(str(explicit).strip())

    raw_keys.append(get_opensubtitles_api_key())
    for env_name in (
        "OPENSUBTITLES_API_KEY_2",
        "OPENSUBTITLES_API_KEY_ALT",
        "OPENSUBTITLES_API_ALTERNATIVE_KEY",
        "OPENSUBTITLES_API_KEY_FALLBACK",
        "opensubtitles_api_alternative_key",
    ):
        raw_keys.append((os.environ.get(env_name) or "").strip())
    raw_keys.extend(_split_env_values(os.environ.get("OPENSUBTITLES_API_KEYS") or ""))

    keys: List[str] = []
    seen = set()
    for key in raw_keys:
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def get_tmdb_api_key() -> str:
    """The Movie Database (TMDB) v3 API key — used for trending/popular TV lists."""
    return (os.environ.get("TMDB_API_KEY") or "").strip()
