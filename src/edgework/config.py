"""Centralized configuration for Edgework.

All secrets and tunables come from environment variables (.env).
Anything you'd want to tweak between runs lives here.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Edgework runtime settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # SoDEX
    sodex_api_key: str = Field(default="", description="SoDEX API key")
    sodex_api_secret: str = Field(default="", description="SoDEX API secret")
    sodex_base_url: str = Field(default="https://api.sodex.com")

    # SoSoValue
    sosovalue_api_key: str = Field(default="", description="SoSoValue API key")
    sosovalue_base_url: str = Field(default="https://openapi.sosovalue.com")

    # Anthropic Claude
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    anthropic_model: str = Field(default="claude-sonnet-4-20250514")

    # Local cache
    data_dir: Path = Field(default=Path("data"))

    def ensure_data_dir(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor.

    Use this everywhere instead of instantiating Settings() directly,
    so we don't reload .env on every call.
    """
    return Settings()
