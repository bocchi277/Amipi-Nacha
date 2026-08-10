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

    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "DEVELOPMENT_SECRET_KEY_CHANGE_IN_PROD_123456789")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day

    model_config = SettingsConfigDict(case_sensitive=True)


settings = Settings()
