"""Centralised application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Any

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.constants.app_constants import (
    APP_NAME_DEFAULT,
    APP_VERSION_DEFAULT,
    DEFAULT_DOWNLOAD_DIR,
    DEFAULT_LOG_DIR,
    DEFAULT_LOG_LEVEL,
    DEFAULT_PAGINATION_SIZE,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_TOP_K,
    MAX_UPLOAD_SIZE_BYTES,
)
from app.constants.aws_constants import (
    AWS_CONNECT_TIMEOUT_DEFAULT,
    AWS_MAX_RETRIES_DEFAULT,
    AWS_READ_TIMEOUT_DEFAULT,
    AWS_REGION_DEFAULT,
    BEDROCK_MAX_TOKENS_DEFAULT,
    BEDROCK_MODEL_ID_DEFAULT,
    BEDROCK_TEMPERATURE_DEFAULT,
    BEDROCK_TOP_P_DEFAULT,
    S3_ACCOUNT_MASTER_FILE_DEFAULT,
    S3_ACCOUNT_MASTER_PREFIX_DEFAULT,
    S3_BUCKET_DEFAULT,
    S3_COST_EXPLORER_PREFIX_DEFAULT,
)
from app.constants.cache_constants import CACHE_TTL_SECONDS
from app.constants.db_constants import (
    BATCH_INSERT_SIZE_DEFAULT,
    DATABASE_URL_DEFAULT,
    DB_MAX_OVERFLOW_DEFAULT,
    DB_POOL_SIZE_DEFAULT,
    DB_POOL_TIMEOUT_DEFAULT,
    POSTGRES_DB_DEFAULT,
    POSTGRES_HOST_DEFAULT,
    POSTGRES_PASSWORD_DEFAULT,
    POSTGRES_PORT_DEFAULT,
    POSTGRES_USER_DEFAULT,
)


class Settings(BaseSettings):
    """Application settings sourced from .env or environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ───────────────────────────────────────────────────────────────────
    app_name: str = Field(default=APP_NAME_DEFAULT, validation_alias=AliasChoices("APP_NAME"))
    app_version: str = Field(default=APP_VERSION_DEFAULT, validation_alias=AliasChoices("APP_VERSION"))
    debug: bool = Field(default=False, validation_alias=AliasChoices("DEBUG"))
    log_level: str = Field(default=DEFAULT_LOG_LEVEL, validation_alias=AliasChoices("LOG_LEVEL"))
    download_dir: str = Field(default=DEFAULT_DOWNLOAD_DIR, validation_alias=AliasChoices("DOWNLOAD_DIR"))
    log_dir: str = Field(default=DEFAULT_LOG_DIR, validation_alias=AliasChoices("LOG_DIR"))

    # ── Authentication ────────────────────────────────────────────────────────
    login_email: str = Field(
        default="infrastructureteam@ssi.safestart.com",
        validation_alias=AliasChoices("LOGIN_EMAIL", "AUTH_EMAIL"),
    )
    login_password: str = Field(
        default="admin@359",
        validation_alias=AliasChoices("LOGIN_PASSWORD", "AUTH_PASSWORD"),
    )
    jwt_secret_key: str = Field(
        default="cloud-cost-intelligence-jwt-secret-key-prod-2026-secure",
        validation_alias=AliasChoices("JWT_SECRET_KEY", "SECRET_KEY"),
    )
    jwt_algorithm: str = Field(default="HS256", validation_alias=AliasChoices("JWT_ALGORITHM"))
    jwt_expire_hours: int = Field(default=24, validation_alias=AliasChoices("JWT_EXPIRE_HOURS"))

    default_top_k: int = Field(default=DEFAULT_TOP_K, validation_alias=AliasChoices("DEFAULT_TOP_K", "TOP_K_RESULTS"))
    default_pagination_size: int = Field(
        default=DEFAULT_PAGINATION_SIZE, validation_alias=AliasChoices("DEFAULT_PAGINATION_SIZE", "PAGINATION_SIZE")
    )
    request_timeout_seconds: int = Field(
        default=DEFAULT_REQUEST_TIMEOUT_SECONDS, validation_alias=AliasChoices("REQUEST_TIMEOUT_SECONDS", "REQUEST_TIMEOUT")
    )
    max_upload_size_bytes: int = Field(
        default=MAX_UPLOAD_SIZE_BYTES, validation_alias=AliasChoices("MAX_UPLOAD_SIZE_BYTES", "UPLOAD_LIMITS")
    )
    cache_ttl_seconds: int = Field(default=CACHE_TTL_SECONDS, validation_alias=AliasChoices("CACHE_TTL_SECONDS", "CACHE_TTL"))

    # ── Single Unified AWS Account ────────────────────────────────────────────
    aws_access_key_id: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AWS_ACCESS_KEY_ID", "S3_AWS_ACCESS_KEY_ID", "BEDROCK_AWS_ACCESS_KEY_ID", "CE_AWS_ACCESS_KEY_ID"
        ),
    )
    aws_secret_access_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AWS_SECRET_ACCESS_KEY", "S3_AWS_SECRET_ACCESS_KEY", "BEDROCK_AWS_SECRET_ACCESS_KEY", "CE_AWS_SECRET_ACCESS_KEY"
        ),
    )
    aws_session_token: str = Field(
        default="",
        validation_alias=AliasChoices("AWS_SESSION_TOKEN", "BEDROCK_AWS_SESSION_TOKEN"),
    )
    aws_region: str = Field(
        default=AWS_REGION_DEFAULT,
        validation_alias=AliasChoices("AWS_REGION", "S3_REGION", "BEDROCK_REGION", "CE_REGION"),
    )

    aws_connect_timeout: int = Field(
        default=AWS_CONNECT_TIMEOUT_DEFAULT, validation_alias=AliasChoices("AWS_CONNECT_TIMEOUT")
    )
    aws_read_timeout: int = Field(
        default=AWS_READ_TIMEOUT_DEFAULT, validation_alias=AliasChoices("AWS_READ_TIMEOUT")
    )
    aws_max_retries: int = Field(
        default=AWS_MAX_RETRIES_DEFAULT, validation_alias=AliasChoices("AWS_MAX_RETRIES", "MAX_RETRIES")
    )

    # ── Amazon S3 ─────────────────────────────────────────────────────────────
    aws_s3_bucket: str = Field(
        default=S3_BUCKET_DEFAULT,
        validation_alias=AliasChoices("AWS_S3_BUCKET", "S3_BUCKET_NAME", "AWS_S3_BUCKET_NAME"),
    )
    aws_account_master_prefix: str = Field(
        default=S3_ACCOUNT_MASTER_PREFIX_DEFAULT,
        validation_alias=AliasChoices("AWS_ACCOUNT_MASTER_PREFIX", "S3_ACCOUNT_MASTER_PREFIX"),
    )
    aws_account_master_file: str = Field(
        default=S3_ACCOUNT_MASTER_FILE_DEFAULT,
        validation_alias=AliasChoices("AWS_ACCOUNT_MASTER_FILE", "S3_ACCOUNT_MASTER_PATH"),
    )
    aws_cost_explorer_prefix: str = Field(
        default=S3_COST_EXPLORER_PREFIX_DEFAULT,
        validation_alias=AliasChoices("AWS_COST_EXPLORER_PREFIX", "S3_COST_REPORTS_DIR"),
    )

    # ── Amazon Bedrock ────────────────────────────────────────────────────────
    bedrock_model_id: str = Field(
        default=BEDROCK_MODEL_ID_DEFAULT,
        validation_alias=AliasChoices("BEDROCK_MODEL_ID"),
    )
    bedrock_max_tokens: int = Field(
        default=BEDROCK_MAX_TOKENS_DEFAULT, validation_alias=AliasChoices("BEDROCK_MAX_TOKENS")
    )
    bedrock_temperature: float = Field(
        default=BEDROCK_TEMPERATURE_DEFAULT, validation_alias=AliasChoices("BEDROCK_TEMPERATURE")
    )
    bedrock_top_p: float = Field(
        default=BEDROCK_TOP_P_DEFAULT, validation_alias=AliasChoices("BEDROCK_TOP_P")
    )

    # ── PostgreSQL ───────────────────────────────────────────────────────────
    database_url: str = Field(
        default=DATABASE_URL_DEFAULT,
        validation_alias=AliasChoices("DATABASE_URL"),
    )
    postgres_host: str = Field(default=POSTGRES_HOST_DEFAULT, validation_alias=AliasChoices("POSTGRES_HOST"))
    postgres_port: int = Field(default=POSTGRES_PORT_DEFAULT, validation_alias=AliasChoices("POSTGRES_PORT"))
    postgres_db: str = Field(default=POSTGRES_DB_DEFAULT, validation_alias=AliasChoices("POSTGRES_DB"))
    postgres_user: str = Field(default=POSTGRES_USER_DEFAULT, validation_alias=AliasChoices("POSTGRES_USER"))
    postgres_password: str = Field(default=POSTGRES_PASSWORD_DEFAULT, validation_alias=AliasChoices("POSTGRES_PASSWORD"))

    db_pool_size: int = Field(default=DB_POOL_SIZE_DEFAULT, validation_alias=AliasChoices("DB_POOL_SIZE"))
    db_max_overflow: int = Field(default=DB_MAX_OVERFLOW_DEFAULT, validation_alias=AliasChoices("DB_MAX_OVERFLOW"))
    db_pool_timeout: int = Field(default=DB_POOL_TIMEOUT_DEFAULT, validation_alias=AliasChoices("DB_POOL_TIMEOUT"))
    batch_insert_size: int = Field(default=BATCH_INSERT_SIZE_DEFAULT, validation_alias=AliasChoices("BATCH_INSERT_SIZE"))

    # ── Backward compatibility helpers ─────────────────────────────────────────
    @property
    def s3_bucket_name(self) -> str:
        return self.aws_s3_bucket

    @property
    def s3_account_master_path(self) -> str:
        return self.aws_account_master_file

    @property
    def s3_cost_reports_dir(self) -> str:
        return self.aws_cost_explorer_prefix

    @property
    def s3_aws_access_key_id(self) -> str:
        return self.aws_access_key_id

    @property
    def s3_aws_secret_access_key(self) -> str:
        return self.aws_secret_access_key

    @property
    def s3_region(self) -> str:
        return self.aws_region

    @property
    def ce_aws_access_key_id(self) -> str:
        return self.aws_access_key_id

    @property
    def ce_aws_secret_access_key(self) -> str:
        return self.aws_secret_access_key

    @property
    def ce_region(self) -> str:
        return self.aws_region

    @property
    def bedrock_aws_access_key_id(self) -> str:
        return self.aws_access_key_id

    @property
    def bedrock_aws_secret_access_key(self) -> str:
        return self.aws_secret_access_key

    @property
    def bedrock_region(self) -> str:
        return self.aws_region

    @field_validator("debug", mode="before")
    @classmethod
    def _coerce_debug(cls, value: Any) -> bool:
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on", "debug"}:
                return True
            if lowered in {"0", "false", "no", "off", "release", "production"}:
                return False
        return bool(value)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton of Settings — safe to call anywhere."""
    return Settings()
