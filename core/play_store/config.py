import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


load_dotenv()


def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    if value is None:
        return default
    stripped = value.strip()
    return stripped or default


def _get_path_env(name: str, default: str) -> Path:
    raw = _get_env(name, default)
    if raw is None:
        raw = default
    return Path(raw).expanduser()


@dataclass(frozen=True)
class Settings:
    default_country: str
    default_language: str
    default_device: str
    search_output_dir: Path
    screenshot_output_dir: Path
    database_path: Path
    http_proxy: Optional[str]


def _load_settings() -> Settings:
    default_country = (_get_env("APP_STORE_DEFAULT_COUNTRY", "tr") or "tr").lower()
    default_language = _get_env("APP_STORE_DEFAULT_LANGUAGE", "en") or "en"
    default_device = (_get_env("APP_STORE_DEFAULT_DEVICE", "iphone") or "iphone").lower()
    return Settings(
        default_country=default_country,
        default_language=default_language,
        default_device=default_device,
        search_output_dir=_get_path_env("APP_STORE_SEARCH_OUTPUT_DIR", "app_store_search_results"),
        screenshot_output_dir=_get_path_env("APP_STORE_SCREENSHOT_OUTPUT_DIR", "app_store_downloads"),
        database_path=_get_path_env("SCREEN_ASO_DB_PATH", "data/screen_aso.db"),
        http_proxy=_get_env("APP_STORE_HTTP_PROXY"),
    )


settings = _load_settings()


def reload_settings(dotenv_path: Optional[Path] = None) -> Settings:
    if dotenv_path is not None:
        load_dotenv(dotenv_path, override=True)
    else:
        load_dotenv(override=True)
    global settings
    settings = _load_settings()
    return settings


__all__ = ["Settings", "settings", "reload_settings"]
