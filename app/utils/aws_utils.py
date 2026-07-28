"""
aws_utils.py — Shared helpers for building boto3 clients / sessions.

Centralises credential handling for a SINGLE UNIFIED AWS ACCOUNT.
All services (S3, Bedrock, Cost Explorer) share the same credential source of truth:
(settings → env vars → IAM role chain).
"""

import logging
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

def get_boto3_config() -> Config:
    """Return a boto3 Config using settings timeouts and max retries."""
    return Config(
        connect_timeout=settings.aws_connect_timeout,
        read_timeout=settings.aws_read_timeout,
        retries={"max_attempts": settings.aws_max_retries, "mode": "adaptive"},
    )


def _credential_kwargs(
    access_key: str | None = None,
    secret_key: str | None = None,
    session_token: str | None = None,
) -> dict[str, str]:
    """Return explicit credential kwargs if set; otherwise empty dict.

    When running on EC2 / ECS / Lambda, boto3 picks up credentials from the
    instance/task IAM role automatically when the dict is empty.
    """
    kw: dict[str, str] = {}
    key = access_key or settings.aws_access_key_id
    secret = secret_key or settings.aws_secret_access_key
    token = session_token or settings.aws_session_token

    if key and secret:
        kw["aws_access_key_id"] = key
        kw["aws_secret_access_key"] = secret
        if token:
            kw["aws_session_token"] = token
    return kw


def get_boto3_client(
    service_name: str,
    region: str | None = None,
    config: Config | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    session_token: str | None = None,
) -> Any:
    """Create and return a boto3 client for *service_name* using single AWS account credentials."""
    kwargs: dict[str, Any] = {
        "region_name": region or settings.aws_region,
        "config": config or get_boto3_config(),
        **_credential_kwargs(access_key, secret_key, session_token),
    }
    try:
        client = boto3.client(service_name, **kwargs)
        logger.debug("Created boto3 client: service=%s region=%s", service_name, kwargs["region_name"])
        return client
    except NoCredentialsError as exc:
        msg = (
            "AWS credentials not found. Set AWS_ACCESS_KEY_ID / "
            "AWS_SECRET_ACCESS_KEY in .env, or attach an IAM role to the host."
        )
        logger.error(msg)
        raise RuntimeError(msg) from exc


def get_boto3_session(
    region: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    session_token: str | None = None,
) -> boto3.Session:
    """Create a boto3 Session using single AWS account credentials."""
    kwargs: dict[str, Any] = {
        "region_name": region or settings.aws_region,
        **_credential_kwargs(access_key, secret_key, session_token),
    }
    return boto3.Session(**kwargs)


def get_s3_session(region: str | None = None) -> boto3.Session:
    """Create a boto3 Session for S3 using single unified AWS account credentials."""
    logger.info("Connecting to S3...")
    return get_boto3_session(region=region or settings.aws_region)


def get_cost_explorer_session(region: str | None = None) -> boto3.Session:
    """Create a boto3 Session for Cost Explorer using single unified AWS account credentials."""
    logger.info("Connecting to Cost Explorer...")
    return get_boto3_session(region=region or settings.aws_region)


def get_bedrock_session(region: str | None = None) -> boto3.Session:
    """Create a boto3 Session for Amazon Bedrock using single unified AWS account credentials."""
    logger.info("Connecting to Bedrock...")
    return get_boto3_session(region=region or settings.aws_region)


def get_cost_optimization_session(region: str | None = None) -> boto3.Session:
    """Create a boto3 Session for Cost Optimization Hub using single unified AWS account credentials."""
    logger.info("Connecting to Cost Optimization Hub...")
    return get_boto3_session(region=region or settings.aws_region)


def get_s3_client(region: str | None = None) -> Any:
    return get_s3_session(region=region).client("s3", config=get_boto3_config())


def get_cost_explorer_client(region: str | None = None) -> Any:
    return get_cost_explorer_session(region=region).client("ce", config=get_boto3_config())


def get_bedrock_client(region: str | None = None) -> Any:
    return get_bedrock_session(region=region).client("bedrock-runtime", config=get_boto3_config())


def get_cost_optimization_client(region: str | None = None) -> Any:
    return get_cost_optimization_session(region=region).client("ce", config=get_boto3_config())


def check_aws_credentials() -> dict[str, Any]:
    """Validate that AWS credentials are resolvable and return caller identity."""
    try:
        sts = get_boto3_client("sts")
        identity = sts.get_caller_identity()
        result = {
            "account_id": identity.get("Account"),
            "user_id": identity.get("UserId"),
            "arn": identity.get("Arn"),
            "region": settings.aws_region,
            "source": "single_aws_account",
        }
        logger.info("AWS credentials valid: account=%s", result["account_id"])
        return result
    except (ClientError, BotoCoreError, RuntimeError) as exc:
        logger.warning("AWS credential check failed: %s", exc)
        raise RuntimeError(f"AWS credential validation failed: {exc}") from exc
