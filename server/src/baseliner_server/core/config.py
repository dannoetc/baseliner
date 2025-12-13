from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    baseliner_token_pepper: str
    baseliner_admin_key: str


settings = Settings()
