from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Timezone
    timezone: str = Field(default="Asia/Singapore")

    # Database (individual MySQL fields)
    mysql_host: str = Field(default="mysql")
    mysql_port: int = Field(default=3306)
    mysql_user: str = Field(default="")
    mysql_password: str = Field(default="")
    mysql_database: str = Field(default="")

    # Telegram
    telegram_bot_token: str = Field(default="")

    # IMAP
    imap_host: str = Field(default="imap.gmail.com")
    imap_port: int = Field(default=993)
    imap_username: str = Field(default="")
    imap_password: str = Field(default="")

    # Polling
    poll_interval_seconds: int = Field(default=60)

    # Health server
    health_port: int = Field(default=8080)
    health_host: str = Field(default="127.0.0.1")

    # Logging
    log_level: str = Field(default="INFO")

    @property
    def database_url(self) -> str:
        # URL-encode credentials so passwords containing @, :, /, etc. don't
        # break the DSN.
        user = quote_plus(self.mysql_user)
        password = quote_plus(self.mysql_password)
        return (
            f"mysql://{user}:{password}@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
        )

    @field_validator("telegram_bot_token")
    @classmethod
    def telegram_bot_token_required(cls, v: str) -> str:
        if not v:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        return v

    @field_validator("imap_username")
    @classmethod
    def imap_username_required(cls, v: str) -> str:
        if not v:
            raise ValueError("IMAP_USERNAME is required")
        return v

    @field_validator("imap_password")
    @classmethod
    def imap_password_required(cls, v: str) -> str:
        if not v:
            raise ValueError("IMAP_PASSWORD is required")
        return v

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_sgt(cls, v: str) -> str:
        if v != "Asia/Singapore":
            raise ValueError("TIMEZONE must be Asia/Singapore")
        return v

    @field_validator("log_level")
    @classmethod
    def log_level_valid(cls, v: str) -> str:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid_levels:
            raise ValueError(f"LOG_LEVEL must be one of {valid_levels}")
        return v.upper()


@lru_cache
def get_settings() -> Settings:
    return Settings()
