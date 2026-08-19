"""Configuration utilities for the GIS mapping agent."""

import os
from pathlib import Path

from dotenv import load_dotenv

from config.hyperparameters import HyperParameters


env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


class Config:
    """Application configuration."""

    HYPERPARAMETERS = HyperParameters
    PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent

    OUTPUT_DIR: Path = PROJECT_ROOT / Path(os.getenv("OUTPUT_DIR", "outputs"))
    TEMP_DIR: Path = PROJECT_ROOT / Path(os.getenv("TEMP_DIR", "temp"))
    DATA_DIRECTORY_BASE: Path = PROJECT_ROOT / Path(os.getenv("DATA_DIRECTORY_BASE", "data"))

    @staticmethod
    def _normalize_base_url(raw_url: str) -> str:
        url = (raw_url or "").strip() or "https://api.openai-proxy.org/v1"
        if "api.deepseek.com" in url and not url.rstrip("/").endswith("/v1"):
            return url.rstrip("/") + "/v1"
        return url

    @staticmethod
    def _resolve_openai_api_key() -> str:
        mapping_key = os.getenv("MAPPING_OPENAI_API_KEY", "").strip()
        fallback_key = os.getenv("OPENAI_API_KEY", "").strip()
        return mapping_key or fallback_key

    OPENAI_BASE_URL: str = _normalize_base_url.__func__(
        os.getenv("MAPPING_OPENAI_BASE_URL") or os.getenv("OPENAI_BASE_URL", "https://api.openai-proxy.org/v1")
    )
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = os.getenv("MAPPING_OPENAI_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    DEFAULT_DPI: int = HyperParameters.DEFAULT_DPI
    DEFAULT_FIGSIZE: tuple = HyperParameters.DEFAULT_FIGSIZE
    DEFAULT_CRS: str = "EPSG:4326"

    @classmethod
    def ensure_directories(cls) -> None:
        for directory in [cls.OUTPUT_DIR, cls.TEMP_DIR]:
            directory.mkdir(parents=True, exist_ok=True)

    @classmethod
    def validate_api_keys(cls) -> dict:
        return {
            "openai": bool(cls.OPENAI_API_KEY),
        }


Config.OPENAI_API_KEY = Config._resolve_openai_api_key()
