"""Enterprise FinOps Copilot — Canonical Entity Resolver.

This module is the single source of truth for all entity resolution.

Key principles:
- STRICT alias lookup only — no fuzzy scoring that can mismap RDS → DMS or EC2 → EFS
- All service aliases are explicit and hand-curated
- Relative date expressions are resolved to exact billing period lists BEFORE retrieval
- The LLM never performs entity resolution or date calculation
"""

from __future__ import annotations

from datetime import date, datetime
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CANONICAL SERVICE ALIAS MAP
# Format: alias_lower → canonical_display_name
# Rules:
#   - No entry may map to a different service (e.g. "rds" MUST map to RDS, never DMS)
#   - Shorter tokens are listed after longer ones to avoid false-prefix matches
#   - Each section is guarded by explicit word-boundary matching in resolve_service()
# ─────────────────────────────────────────────────────────────────────────────

# Map of aliases → canonical AWS billing display name
# This is the ONLY place aliases are defined.
_CANONICAL_ALIAS_MAP: dict[str, str] = {
    # ── Amazon EC2 ────────────────────────────────────────────────────────────
    "amazon ec2": "Amazon EC2",
    "ec2": "Amazon EC2",
    "elastic compute cloud": "Amazon EC2",
    "elastic compute": "Amazon EC2",
    "virtual machine": "Amazon EC2",
    "virtual machines": "Amazon EC2",
    "vm": "Amazon EC2",
    "vms": "Amazon EC2",
    "compute instance": "Amazon EC2",
    "compute instances": "Amazon EC2",
    # ── AWS Lambda ────────────────────────────────────────────────────────────
    "aws lambda": "AWS Lambda",
    "lambda": "AWS Lambda",
    "serverless": "AWS Lambda",
    "serverless function": "AWS Lambda",
    "serverless functions": "AWS Lambda",
    # ── Amazon S3 ─────────────────────────────────────────────────────────────
    "amazon s3": "Amazon S3",
    "s3": "Amazon S3",
    "simple storage service": "Amazon S3",
    "simple storage": "Amazon S3",
    "object storage": "Amazon S3",
    "object store": "Amazon S3",
    "s3 bucket": "Amazon S3",
    "s3 buckets": "Amazon S3",
    # ── Amazon RDS ────────────────────────────────────────────────────────────
    "amazon rds": "Amazon RDS",
    "rds": "Amazon RDS",
    "relational database service": "Amazon RDS",
    "relational database": "Amazon RDS",
    "managed database": "Amazon RDS",
    "managed databases": "Amazon RDS",
    "aurora": "Amazon RDS",
    "postgres": "Amazon RDS",
    "postgresql": "Amazon RDS",
    "mysql": "Amazon RDS",
    # ── Amazon DynamoDB ───────────────────────────────────────────────────────
    "amazon dynamodb": "Amazon DynamoDB",
    "dynamodb": "Amazon DynamoDB",
    "dynamo db": "Amazon DynamoDB",
    "dynamo": "Amazon DynamoDB",
    "nosql": "Amazon DynamoDB",
    # ── Amazon ECS ────────────────────────────────────────────────────────────
    "amazon ecs": "Amazon ECS",
    "ecs": "Amazon ECS",
    "elastic container service": "Amazon ECS",
    "container service": "Amazon ECS",
    # ── Amazon EKS ────────────────────────────────────────────────────────────
    "amazon eks": "Amazon EKS",
    "eks": "Amazon EKS",
    "elastic kubernetes service": "Amazon EKS",
    "kubernetes": "Amazon EKS",
    "k8s": "Amazon EKS",
    # ── Amazon ECR ────────────────────────────────────────────────────────────
    "amazon ecr": "Amazon ECR",
    "ecr": "Amazon ECR",
    "elastic container registry": "Amazon ECR",
    "container registry": "Amazon ECR",
    # ── Amazon EFS ────────────────────────────────────────────────────────────
    "amazon efs": "Amazon EFS",
    "efs": "Amazon EFS",
    "elastic file system": "Amazon EFS",
    "managed file system": "Amazon EFS",
    # ── Amazon CloudFront ─────────────────────────────────────────────────────
    "amazon cloudfront": "Amazon CloudFront",
    "cloudfront": "Amazon CloudFront",
    "cloud front": "Amazon CloudFront",
    "cdn": "Amazon CloudFront",
    "content delivery network": "Amazon CloudFront",
    # ── Amazon CloudWatch ─────────────────────────────────────────────────────
    "amazon cloudwatch": "Amazon CloudWatch",
    "cloudwatch": "Amazon CloudWatch",
    "cloud watch": "Amazon CloudWatch",
    "monitoring": "Amazon CloudWatch",
    # ── Amazon Cognito ────────────────────────────────────────────────────────
    "amazon cognito": "Amazon Cognito",
    "cognito": "Amazon Cognito",
    "user pool": "Amazon Cognito",
    "identity pool": "Amazon Cognito",
    # ── Amazon Kinesis ────────────────────────────────────────────────────────
    "amazon kinesis": "Amazon Kinesis",
    "kinesis": "Amazon Kinesis",
    "kinesis streams": "Amazon Kinesis",
    "data streams": "Amazon Kinesis",
    # ── Amazon SQS ────────────────────────────────────────────────────────────
    "amazon sqs": "Amazon SQS",
    "sqs": "Amazon SQS",
    "simple queue service": "Amazon SQS",
    "simple queue": "Amazon SQS",
    "message queue": "Amazon SQS",
    # ── Amazon SNS ────────────────────────────────────────────────────────────
    "amazon sns": "Amazon SNS",
    "sns": "Amazon SNS",
    "simple notification service": "Amazon SNS",
    "simple notification": "Amazon SNS",
    "push notification": "Amazon SNS",
    # ── Amazon SES ────────────────────────────────────────────────────────────
    "amazon ses": "Amazon SES",
    "ses": "Amazon SES",
    "simple email service": "Amazon SES",
    "simple email": "Amazon SES",
    "email service": "Amazon SES",
    # ── Amazon Route 53 ───────────────────────────────────────────────────────
    "amazon route 53": "Amazon Route 53",
    "route 53": "Amazon Route 53",
    "route53": "Amazon Route 53",
    "dns": "Amazon Route 53",
    # ── Amazon Bedrock ────────────────────────────────────────────────────────
    "amazon bedrock": "Amazon Bedrock",
    "bedrock": "Amazon Bedrock",
    "claude": "Amazon Bedrock",
    "haiku": "Amazon Bedrock",
    "sonnet": "Amazon Bedrock",
    "opus": "Amazon Bedrock",
    "bedrock claude": "Amazon Bedrock",
    # ── AWS Elemental MediaConvert ────────────────────────────────────────────
    "aws elemental mediaconvert": "AWS Elemental MediaConvert",
    "aws mediaconvert": "AWS Elemental MediaConvert",
    "elemental mediaconvert": "AWS Elemental MediaConvert",
    "mediaconvert": "AWS Elemental MediaConvert",
    "media convert": "AWS Elemental MediaConvert",
    "video processing": "AWS Elemental MediaConvert",
    "video transcoding": "AWS Elemental MediaConvert",
    # ── AWS Glue ─────────────────────────────────────────────────────────────
    "aws glue": "AWS Glue",
    "glue": "AWS Glue",
    "data integration": "AWS Glue",
    "etl service": "AWS Glue",
    # ── AWS Backup ────────────────────────────────────────────────────────────
    "aws backup": "AWS Backup",
    "backup": "AWS Backup",
    "managed backup": "AWS Backup",
    # ── Amazon GuardDuty ─────────────────────────────────────────────────────
    "amazon guardduty": "Amazon GuardDuty",
    "guardduty": "Amazon GuardDuty",
    "guard duty": "Amazon GuardDuty",
    "threat detection": "Amazon GuardDuty",
    "security monitoring": "Amazon GuardDuty",
    # ── AWS CloudFormation ────────────────────────────────────────────────────
    "aws cloudformation": "AWS CloudFormation",
    "cloudformation": "AWS CloudFormation",
    "cloud formation": "AWS CloudFormation",
    "infrastructure as code": "AWS CloudFormation",
    "iac": "AWS CloudFormation",
    # ── AWS Secrets Manager ───────────────────────────────────────────────────
    "aws secrets manager": "AWS Secrets Manager",
    "secrets manager": "AWS Secrets Manager",
    "secretsmanager": "AWS Secrets Manager",
    # ── Amazon VPC ────────────────────────────────────────────────────────────
    "amazon vpc": "Amazon VPC",
    "vpc": "Amazon VPC",
    "virtual private cloud": "Amazon VPC",
    "virtual network": "Amazon VPC",
    # ── AWS IAM ───────────────────────────────────────────────────────────────
    "aws iam": "AWS IAM",
    "iam": "AWS IAM",
    "identity and access management": "AWS IAM",
    "access management": "AWS IAM",
    # ── AWS Transfer Family ───────────────────────────────────────────────────
    "aws transfer family": "AWS Transfer Family",
    "transfer family": "AWS Transfer Family",
    "sftp": "AWS Transfer Family",
    # ── Amazon OpenSearch / Elasticsearch ─────────────────────────────────────
    "amazon opensearch service": "Amazon OpenSearch Service",
    "amazon opensearch": "Amazon OpenSearch Service",
    "opensearch service": "Amazon OpenSearch Service",
    "opensearch": "Amazon OpenSearch Service",
    "elasticsearch": "Amazon OpenSearch Service",
    "elastic search": "Amazon OpenSearch Service",
    # ── Amazon API Gateway ───────────────────────────────────────────────────
    "amazon api gateway": "Amazon API Gateway",
    "aws api gateway": "Amazon API Gateway",
    "api gateway": "Amazon API Gateway",
    "gateway": "Amazon API Gateway",
    # ── AWS Database Migration Service (DMS) ──────────────────────────────────
    "aws database migration service": "AWS Database Migration Service",
    "database migration service": "AWS Database Migration Service",
    "aws dms": "AWS Database Migration Service",
    "dms": "AWS Database Migration Service",
    # ── AWS CloudTrail ────────────────────────────────────────────────────────
    "aws cloudtrail": "AWS CloudTrail",
    "cloudtrail": "AWS CloudTrail",
    "cloud trail": "AWS CloudTrail",
    # ── Amazon Athena ─────────────────────────────────────────────────────────
    "amazon athena": "Amazon Athena",
    "athena": "Amazon Athena",
    # ── AWS Config ────────────────────────────────────────────────────────────
    "aws config": "AWS Config",
    "config": "AWS Config",
    # ── AWS WAF ───────────────────────────────────────────────────────────────
    "aws waf": "AWS WAF",
    "waf": "AWS WAF",
    "web application firewall": "AWS WAF",
    # ── Elastic Load Balancing ────────────────────────────────────────────────
    "elastic load balancing": "Elastic Load Balancing",
    "elastic load balancer": "Elastic Load Balancing",
    "load balancer": "Elastic Load Balancing",
    "elb": "Elastic Load Balancing",
    "alb": "Elastic Load Balancing",
    "nlb": "Elastic Load Balancing",
    # ── Amazon ElastiCache ────────────────────────────────────────────────────
    "amazon elasticache": "Amazon ElastiCache",
    "elasticache": "Amazon ElastiCache",
    "redis": "Amazon ElastiCache",
    "memcached": "Amazon ElastiCache",
    # ── Amazon Redshift ───────────────────────────────────────────────────────
    "amazon redshift": "Amazon Redshift",
    "redshift": "Amazon Redshift",
    "data warehouse": "Amazon Redshift",
    # ── AWS KMS ───────────────────────────────────────────────────────────────
    "aws kms": "AWS Key Management Service",
    "kms": "AWS Key Management Service",
    "key management service": "AWS Key Management Service",
    # ── AWS Cost Explorer ─────────────────────────────────────────────────────
    "aws cost explorer": "AWS Cost Explorer",
    "cost explorer": "AWS Cost Explorer",
}

# Sorted by length descending so longer matches take priority (e.g. "elastic container service" before "elastic")
_SORTED_ALIASES = sorted(_CANONICAL_ALIAS_MAP.keys(), key=len, reverse=True)


def resolve_canonical_service(user_input: str) -> str | None:
    """Resolve any user service alias to its canonical AWS billing display name.

    Uses strict prefix/exact matching against curated map with generic prefix fallback.
    """
    if not user_input:
        return None

    normalized = " ".join(user_input.strip().lower().split())

    # 1. Exact match against curated alias map
    for alias in _SORTED_ALIASES:
        if normalized == alias:
            return _CANONICAL_ALIAS_MAP[alias]

    # 2. Token-boundary match against curated alias map
    for alias in _SORTED_ALIASES:
        pattern = r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])"
        if re.search(pattern, normalized):
            return _CANONICAL_ALIAS_MAP[alias]

    # 3. Generic prefix stripping fallback ("aws X", "amazon X" -> match base name)
    clean_text = re.sub(r"^(?:aws|amazon)\s+", "", normalized).strip()
    if clean_text:
        for alias, canonical in _CANONICAL_ALIAS_MAP.items():
            clean_alias = re.sub(r"^(?:aws|amazon)\s+", "", alias).strip()
            if clean_text == clean_alias:
                return canonical

    return None


def extract_service_from_text(
    text: str,
    available_service_names: list[str] | None = None,
) -> str | None:
    """Extract and canonically resolve the primary service mentioned in text.

    1. Matches directly against DB service names (full and prefix-stripped)
    2. Uses curated alias map with strict token-boundary matching
    """
    normalized = " ".join(text.strip().lower().split())

    # Try extraction directly against DB service names if available (longest first)
    if available_service_names:
        sorted_db_services = sorted([s for s in available_service_names if s], key=len, reverse=True)
        for db_svc in sorted_db_services:
            db_norm = db_svc.lower()
            pattern = r"(?<![a-z0-9])" + re.escape(db_norm) + r"(?![a-z0-9])"
            if re.search(pattern, normalized):
                logger.debug("EntityResolver: Direct DB match '%s' in question", db_svc)
                return db_svc
            stripped_db = re.sub(r"^(?:aws|amazon)\s+", "", db_norm).strip()
            if len(stripped_db) >= 3:
                pattern_stripped = r"(?<![a-z0-9])" + re.escape(stripped_db) + r"(?![a-z0-9])"
                if re.search(pattern_stripped, normalized):
                    logger.debug("EntityResolver: Stripped DB match '%s' ('%s') in question", db_svc, stripped_db)
                    return db_svc

    # Try each curated alias (longest first)
    for alias in _SORTED_ALIASES:
        pattern = r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])"
        if re.search(pattern, normalized):
            canonical = _CANONICAL_ALIAS_MAP[alias]
            if available_service_names:
                db_name = resolve_service_against_db(canonical, available_service_names)
                if db_name:
                    logger.debug("EntityResolver: '%s' → alias '%s' → canonical '%s' → DB '%s'",
                                 text[:50], alias, canonical, db_name)
                    return db_name
            logger.debug("EntityResolver: '%s' → alias '%s' → canonical '%s'",
                         text[:50], alias, canonical)
            return canonical

    return None


def validate_startup_service_aliases(available_service_names: list[str]) -> dict[str, Any]:
    """Startup audit comparing distinct DB services against EntityResolver maps."""
    mapped: list[str] = []
    unmapped: list[str] = []

    for svc in available_service_names:
        if not svc:
            continue
        resolved = resolve_service_against_db(svc, available_service_names)
        if resolved:
            mapped.append(svc)
        else:
            unmapped.append(svc)

    logger.info(
        "[STARTUP ALIAS AUDIT] Total DB Services: %d | Mapped: %d | Unmapped: %d",
        len(available_service_names), len(mapped), len(unmapped)
    )
    if unmapped:
        logger.warning("[STARTUP ALIAS AUDIT] DB Services lacking explicit alias mapping: %s", unmapped)

    return {
        "total": len(available_service_names),
        "mapped": mapped,
        "unmapped": unmapped,
    }


# ─────────────────────────────────────────────────────────────────────────────
# SERVICE CATEGORY MAP
# Maps canonical service name → broad category for suggestion fallback
# ─────────────────────────────────────────────────────────────────────────────

_SERVICE_CATEGORIES: dict[str, str] = {
    "Amazon EC2": "compute",
    "AWS Lambda": "compute",
    "Amazon ECS": "compute",
    "Amazon EKS": "compute",
    "Amazon S3": "storage",
    "Amazon EFS": "storage",
    "AWS Backup": "storage",
    "Amazon RDS": "database",
    "Amazon DynamoDB": "database",
    "Amazon OpenSearch Service": "database",
    "Amazon CloudFront": "networking",
    "Amazon Route 53": "networking",
    "Amazon VPC": "networking",
    "Amazon CloudWatch": "operations",
    "AWS CloudFormation": "operations",
    "AWS IAM": "operations",
    "AWS Secrets Manager": "security",
    "Amazon GuardDuty": "security",
    "Amazon Cognito": "security",
    "Amazon SQS": "messaging",
    "Amazon SNS": "messaging",
    "Amazon SES": "messaging",
    "Amazon Kinesis": "messaging",
    "Amazon Bedrock": "ai",
    "AWS Glue": "data",
    "Amazon ECR": "containers",
    "AWS Elemental MediaConvert": "media",
    "AWS Transfer Family": "transfer",
}


# ─────────────────────────────────────────────────────────────────────────────
# MONTH ALIASES (for relative date resolution)
# ─────────────────────────────────────────────────────────────────────────────

_MONTH_NUM: dict[str, int] = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


# ─────────────────────────────────────────────────────────────────────────────
# ABBREVIATION EXPANSION TABLE
# Maps known AWS service abbreviations → set of expanded word tokens
# Used in resolve_service_against_db to match abbreviated canonical names
# against fully-spelled DB service names.
# e.g. "Amazon EFS" canonical → tokens {"efs"} will NOT match
#       "Amazon Elastic File System" DB tokens {"elastic","file","system"}
#      → this table bridges that gap.
# ─────────────────────────────────────────────────────────────────────────────

_ABBREV_TO_EXPANDED_TOKENS: dict[str, set[str]] = {
    "ec2":       {"elastic", "compute"},
    "ecs":       {"elastic", "container"},
    "eks":       {"elastic", "kubernetes"},
    "ecr":       {"elastic", "container", "registry"},
    "efs":       {"elastic", "file", "system"},
    "rds":       {"relational", "database"},
    "sqs":       {"simple", "queue"},
    "sns":       {"simple", "notification"},
    "ses":       {"simple", "email"},
    "iam":       {"identity", "access", "management"},
    "vpc":       {"virtual", "private", "cloud"},
    "s3":        {"simple", "storage"},
    "cdn":       {"cloudfront"},
    "dns":       {"route"},
}


def resolve_service_against_db(
    user_input: str,
    available_service_names: list[str],
) -> str | None:
    """Resolve user service input → canonical name that actually EXISTS in the DB.

    Algorithm:
    1. Resolve user input to a canonical name via strict alias map
    2. Exact case-insensitive match against DB service names
    3. Token-subset match (handles "Amazon EC2" vs "Amazon Elastic Compute Cloud")
    4. Abbreviation-expansion match (handles "Amazon EFS" vs "Amazon Elastic File System")
    """
    canonical = resolve_canonical_service(user_input)
    if not canonical:
        return None

    canonical_lower = canonical.lower()

    # ── 1. Exact match ────────────────────────────────────────────────────────
    for db_name in available_service_names:
        if db_name and db_name.lower() == canonical_lower:
            return db_name

    _ignored = {"amazon", "aws", "service", "services"}
    canonical_tokens = set(re.findall(r"[a-z0-9]+", canonical_lower)) - _ignored

    # ── 2. Token-subset match ────────────────────────────────────────────────────
    for db_name in available_service_names:
        if not db_name:
            continue
        db_lower = db_name.lower()
        db_tokens = set(re.findall(r"[a-z0-9]+", db_lower)) - _ignored
        if canonical_tokens and canonical_tokens.issubset(db_tokens):
            return db_name

    # ── 3. Abbreviation-expansion match ───────────────────────────────────────
    for short_token in canonical_tokens:
        expanded = _ABBREV_TO_EXPANDED_TOKENS.get(short_token)
        if not expanded:
            continue
        for db_name in available_service_names:
            if not db_name:
                continue
            db_lower = db_name.lower()
            db_tokens = set(re.findall(r"[a-z0-9]+", db_lower)) - _ignored
            if expanded.issubset(db_tokens):
                return db_name

    return None


def get_service_category(canonical_name: str) -> str:
    """Return the broad category for a canonical service name (for fallback suggestions)."""
    return _SERVICE_CATEGORIES.get(canonical_name, "other")


def get_services_in_category(category: str) -> list[str]:
    """Return all canonical services in a given category."""
    return [svc for svc, cat in _SERVICE_CATEGORIES.items() if cat == category]


# ─────────────────────────────────────────────────────────────────────────────
# RELATIVE DATE RESOLUTION
# ─────────────────────────────────────────────────────────────────────────────

def _period_from_ym(year: int, month: int) -> str:
    return f"{year}-{month:02d}"


def _subtract_months(year: int, month: int, n: int) -> tuple[int, int]:
    """Subtract n months from (year, month), returning (new_year, new_month)."""
    total = (year - 1) * 12 + (month - 1) - n
    return (total // 12) + 1, (total % 12) + 1


def resolve_relative_date_range(
    text: str,
    available_periods: list[str],
    latest_period: str | None = None,
    current_date: date | None = None,
) -> list[str] | None:
    """Resolve relative date expressions to a list of exact billing periods.

    Anchor selection:
    - "last X" expressions use TODAY as anchor (not the DB's latest period).
    - "this/current" expressions use the DB's latest_period.
    """
    if not available_periods:
        return None

    text_lower = text.lower()
    sorted_periods = sorted(available_periods)

    db_latest = latest_period or (sorted_periods[-1] if sorted_periods else None)
    if not db_latest:
        return None
    try:
        db_year = int(db_latest[:4])
        db_month = int(db_latest[5:7])
    except (ValueError, IndexError):
        return None

    today = current_date or datetime.now().date()
    today_year = today.year
    today_month = today.month

    matched_periods: list[str] | None = None

    # ── "last N months" ──────────────────────────────────────────────────────
    match = re.search(r"\b(?:last|past|previous)\s+(\d+)\s+months?\b", text_lower)
    if match:
        n = int(match.group(1))
        target: list[str] = []
        for i in range(n - 1, -1, -1):
            y, m = _subtract_months(today_year, today_month, i)
            p = _period_from_ym(y, m)
            if p in sorted_periods:
                target.append(p)
        matched_periods = target

    # ── "last quarter" ────────────────────────────────────────────────────────
    elif re.search(r"\b(?:last|past|previous)\s+quarter\b", text_lower):
        qstart_month = ((today_month - 1) // 3) * 3 + 1
        q_start_y, q_start_m = _subtract_months(today_year, qstart_month, 3)
        target = []
        for i in range(3):
            y, m = q_start_y, q_start_m + i
            if m > 12:
                y += 1
                m -= 12
            p = _period_from_ym(y, m)
            if p in sorted_periods:
                target.append(p)
        matched_periods = target

    # ── "this quarter" ─────────────────────────────────────────────────────────
    elif re.search(r"\b(?:current|this)\s+quarter\b", text_lower):
        qstart_month = ((today_month - 1) // 3) * 3 + 1
        target = []
        for i in range(3):
            m = qstart_month + i
            if m > 12:
                break
            p = _period_from_ym(today_year, m)
            if p in sorted_periods:
                target.append(p)
        matched_periods = target

    # ── "last year" / "past 12 months" ───────────────────────────────────────
    elif re.search(r"\b(?:last|past|previous)\s+(?:year|12\s*months?)\b", text_lower):
        target = []
        for i in range(11, -1, -1):
            y, m = _subtract_months(today_year, today_month, i)
            p = _period_from_ym(y, m)
            if p in sorted_periods:
                target.append(p)
        matched_periods = target

    # ── "this year" ────────────────────────────────────────────────────────────
    elif re.search(r"\b(?:current|this)\s+year\b", text_lower):
        target = [p for p in sorted_periods if p.startswith(str(today_year))]
        matched_periods = target

    # ── "last month" ────────────────────────────────────────────────────────────
    elif re.search(r"\b(?:last|previous)\s+month\b", text_lower):
        y, m = _subtract_months(today_year, today_month, 1)
        p = _period_from_ym(y, m)
        matched_periods = [p] if p in sorted_periods else []

    # ── "this month" ────────────────────────────────────────────────────────────
    elif re.search(r"\b(?:this|current)\s+month\b", text_lower):
        matched_periods = [db_latest] if db_latest in sorted_periods else []

    return matched_periods


def detect_relative_date_type(text: str) -> str | None:
    """Detect if the text contains a relative date expression and return its type.

    Returns one of: "last_n_months", "last_quarter", "current_quarter",
                    "last_year", "current_year", "last_month", "this_month"
    Returns None if no relative date expression detected.
    """
    text_lower = text.lower()

    if re.search(r"\b(?:last|past|previous)\s+\d+\s+months?\b", text_lower):
        return "last_n_months"
    if re.search(r"\b(?:last|past|previous)\s+quarter\b", text_lower):
        return "last_quarter"
    if re.search(r"\b(?:current|this)\s+quarter\b", text_lower):
        return "current_quarter"
    if re.search(r"\b(?:last|past|previous)\s+(?:year|12\s*months?)\b", text_lower):
        return "last_year"
    if re.search(r"\b(?:current|this)\s+year\b", text_lower):
        return "current_year"
    if re.search(r"\b(?:last|previous)\s+month\b", text_lower):
        return "last_month"
    if re.search(r"\b(?:this|current)\s+month\b", text_lower):
        return "this_month"
    return None


def extract_comparison_service_from_text(
    text: str,
    available_service_names: list[str] | None = None,
    primary_service: str | None = None,
) -> str | None:
    """Extract a second service for comparison queries.

    Only returns a service if it is different from the primary service.
    """
    normalized = " ".join(text.strip().lower().split())
    primary_lower = (primary_service or "").lower()

    found: list[str] = []
    matched_spans: list[tuple[int, int]] = []

    for alias in _SORTED_ALIASES:
        pattern = r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])"
        for m in re.finditer(pattern, normalized):
            # Check if this span overlaps with any already matched
            span_start, span_end = m.start(), m.end()
            if any(s <= span_start < e or s < span_end <= e for s, e in matched_spans):
                continue
            canonical = _CANONICAL_ALIAS_MAP[alias]
            if canonical.lower() != primary_lower and canonical not in found:
                found.append(canonical)
                matched_spans.append((span_start, span_end))

    for candidate in found:
        if available_service_names:
            db_name = resolve_service_against_db(candidate, available_service_names)
            if db_name:
                return db_name
        return candidate  # Return canonical even if not in DB (for validation guard)

    return None
