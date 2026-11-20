import secrets

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration with safe local-development defaults."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./rfq.db"
    # Keep local startup convenient without shipping a predictable JWT signing
    # key. Set SECRET_KEY explicitly anywhere tokens must survive restarts.
    secret_key: SecretStr = SecretStr(secrets.token_urlsafe(48))
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    frontend_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:8000"
    page_size: int = 20
    rate_limit_per_minute: int = 120

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
