"""Application configuration loaded from environment variables via pydantic-settings."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    llama_server_url: str = "http://localhost:8080"
    llama_model_name: str = "tinyllama"
    api_secret_key: str
    log_level: str = "INFO"

    # Stored as a plain string so pydantic-settings doesn't try to JSON-decode it.
    # Use the cors_origins property everywhere — it returns list[str].
    cors_origins_raw: str = Field(default="http://localhost:5173", alias="CORS_ORIGINS")

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]


settings = Settings()
