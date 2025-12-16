from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# core/config.py -> baseliner_server/core/config.py
# parents:
#   [0] core
#   [1] baseliner_server
#   [2] src
#   [3] server
_SERVER_DIR = Path(__file__).resolve().parents[3]
_ENV_FILE = _SERVER_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    database_url: str
    baseliner_token_pepper: str
    baseliner_admin_key: str


settings = Settings()
