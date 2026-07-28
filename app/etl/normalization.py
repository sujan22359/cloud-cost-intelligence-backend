import logging
from app.services.business_cost_service import resolve_service_name_alias

logger = logging.getLogger(__name__)


def normalize_service_name(raw_service_name: str) -> str:
    """Normalize raw service names to canonical business service names.

    Examples:
    Amazon Elastic Compute Cloud - Compute
    Amazon Elastic Compute Cloud - Other
    → Amazon EC2

    All Bedrock model names
    → Amazon Bedrock
    """
    if not raw_service_name:
        return ""

    name_lower = raw_service_name.strip().lower()

    # Normalize EC2 Compute variants
    if "elastic compute cloud" in name_lower or name_lower == "amazon ec2" or name_lower == "ec2":
        return "Amazon EC2"

    # Normalize Bedrock models
    if any(k in name_lower for k in ("bedrock", "claude", "haiku", "sonnet", "opus", "nova-lite", "nova-pro")):
        return "Amazon Bedrock"

    # Return standard alias mapping
    return resolve_service_name_alias(raw_service_name)
