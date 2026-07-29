"""AWS Secrets Manager integration module.

Retrieves JSON secrets from AWS Secrets Manager once during startup and caches
them in memory. Falls back to local environment variables / .env if SECRET_NAME is not configured.
"""

import json
import logging
import os
from functools import lru_cache
from typing import Any, Dict

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def fetch_secrets_from_secrets_manager() -> Dict[str, Any]:
    """Fetch JSON secret dictionary from AWS Secrets Manager.

    Reads SECRET_NAME from environment variables.
    If SECRET_NAME is not set or empty, returns an empty dictionary (local dev fallback).
    Caches results in memory using @lru_cache to prevent repeated network calls.

    Returns:
        Dict[str, Any]: Parsed JSON dictionary of secret key-value pairs.

    Raises:
        RuntimeError: If SECRET_NAME is set but retrieval from AWS Secrets Manager fails.
        ValueError: If the secret payload is invalid or not valid JSON.
    """
    secret_name = os.getenv("SECRET_NAME") or os.getenv("AWS_SECRET_NAME")
    if not secret_name:
        logger.info("SECRET_NAME environment variable not set. Using local .env / environment fallback.")
        return {}

    region_name = os.getenv("AWS_REGION") or os.getenv("BEDROCK_REGION") or "us-east-1"
    logger.info("Fetching secrets from AWS Secrets Manager secret: '%s' (region: %s)...", secret_name, region_name)

    try:
        session = boto3.session.Session()
        client = session.client(service_name="secretsmanager", region_name=region_name)
        response = client.get_secret_value(SecretId=secret_name)
    except (ClientError, BotoCoreError) as exc:
        logger.error("Failed to retrieve secret '%s' from AWS Secrets Manager: %s", secret_name, exc)
        raise RuntimeError(
            f"Failed to load secrets from AWS Secrets Manager for secret '{secret_name}': {exc}"
        ) from exc

    if "SecretString" in response:
        secret_data = response["SecretString"]
        try:
            secrets_dict = json.loads(secret_data)
            logger.info("Successfully loaded and parsed %d secrets from AWS Secrets Manager.", len(secrets_dict))
            return secrets_dict
        except json.JSONDecodeError as exc:
            logger.error("Secret '%s' in Secrets Manager is not valid JSON: %s", secret_name, exc)
            raise ValueError(f"Secret '{secret_name}' is not valid JSON payload") from exc
    else:
        logger.error("Secret '%s' in Secrets Manager contains binary payload which is not supported.", secret_name)
        raise ValueError(f"Secret '{secret_name}' does not contain a text SecretString payload")
