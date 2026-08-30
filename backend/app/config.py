"""
Application configuration using Pydantic Settings V2.
"""
import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "AMIPI NACHA ACH Payment System"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"

    # Database configuration
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://amipi:amipipass@localhost:5432/amipi_ach"
    )
    SYNC_DATABASE_URL: str = os.getenv(
        "SYNC_DATABASE_URL",
        "postgresql+psycopg2://amipi:amipipass@localhost:5432/amipi_ach"
    )

    # CORS configuration
    ALLOWED_ORIGINS: str = os.getenv("ALLOWED_ORIGINS", "*")

    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "DEVELOPMENT_SECRET_KEY_CHANGE_IN_PROD_123456789")
    ALGORITHM: str = "HS256"
    # See app/core/security.py for why this is 8 hours rather than a day.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8  # one working day

    model_config = SettingsConfigDict(case_sensitive=True)

    def get_async_database_url(self) -> str:
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

        # asyncpg expects 'ssl' parameter instead of 'sslmode' and ignores 'channel_binding'
        url = url.replace("sslmode=require", "ssl=require")
        url = url.replace("sslmode=prefer", "ssl=prefer")
        url = url.replace("sslmode=verify-full", "ssl=verify-full")
        url = url.replace("sslmode=disable", "ssl=disable")

        if "&channel_binding=" in url:
            url = url.split("&channel_binding=")[0]
        elif "?channel_binding=" in url:
            url = url.split("?channel_binding=")[0]

        return url


    def get_sync_database_url(self) -> str:
        if "SYNC_DATABASE_URL" in os.environ:
            return os.environ["SYNC_DATABASE_URL"]
        url = self.DATABASE_URL
        if url.startswith("postgresql+asyncpg://"):
            return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
        elif url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif url.startswith("postgresql://") and not url.startswith("postgresql+psycopg2://"):
            return url.replace("postgresql://", "postgresql+psycopg2://", 1)
        return url


settings = Settings()
# Ensure settings.DATABASE_URL uses asyncpg driver and SYNC_DATABASE_URL uses psycopg2 driver
settings.SYNC_DATABASE_URL = settings.get_sync_database_url()
settings.DATABASE_URL = settings.get_async_database_url()


