import re
from typing import List, Set


# Dictionary of known entities by category
ENTITY_DICTIONARY = {
    # AWS Services
    "AWS Services": [
        "EC2", "Lambda", "API Gateway", "CloudWatch", "RDS", "DMS", "S3", "ECS",
        "EKS", "DynamoDB", "Cognito", "Glue", "GuardDuty", "MediaConvert", "CloudFront",
        "ECR", "Route53", "SNS", "SQS", "ElastiCache", "Secrets Manager", "IAM",
        "KMS", "Redshift", "Athena", "Bedrock", "Cost Explorer", "CloudTrail", "ALB", "NLB"
    ],
    # Products
    "Products": [
        "SafeStart", "AccuTrain"
    ],
    # Environments
    "Environments": [
        "Development", "Dev", "QA", "UAT", "Production", "Prod", "Staging", "Sandbox"
    ],
    # Infrastructure Terms
    "Infrastructure Terms": [
        "Migration", "Serverless", "Pull Request", "Reserved Instance", "Savings Plan",
        "Auto Scaling", "Rightsizing", "Container", "Docker", "Microservices", "Cluster",
        "Load Balancer", "VPC", "Subnet", "Single Merge Commit", "CI/CD", "Terraform"
    ],
    # Optimization Terms
    "Optimization Terms": [
        "Cost Optimization", "Optimization", "Savings", "Unused Resources", "Idle Resources",
        "Wastage", "Overprovisioned", "Spot Instance", "Cost Reduction", "Underutilized"
    ],
    # Business Terms
    "Business Terms": [
        "Meeting", "Architecture", "Deployment", "Scaling", "Performance", "Budget",
        "Recommendation", "Review", "Strategy", "Minutes", "Cost Call"
    ]
}

# Stopwords to filter out generic words during secondary keyword extraction
STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren't",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by",
    "can", "could", "did", "do", "does", "doing", "down", "during", "each", "few", "for", "from", "further",
    "had", "has", "have", "having", "he", "her", "here", "hers", "herself", "him", "himself", "his", "how",
    "i", "if", "in", "into", "is", "it", "its", "itself", "just", "me", "more", "most", "my", "myself",
    "no", "nor", "not", "now", "of", "off", "on", "once", "only", "or", "other", "our", "ours", "ourselves",
    "out", "over", "own", "s", "same", "she", "should", "so", "some", "such", "than", "that", "the", "their",
    "theirs", "them", "themselves", "then", "there", "these", "they", "this", "those", "through", "to", "too",
    "under", "until", "up", "very", "was", "we", "were", "what", "when", "where", "which", "while", "who",
    "whom", "why", "with", "would", "you", "your", "yours", "yourself", "yourselves",
    "hello", "team", "today", "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december"
}


class KeywordExtractionService:
    """Deterministic lightweight automatic keyword extraction service.
    
    Uses dictionary matching, regex pattern extraction, entity detection,
    and tokenization without making external LLM or Bedrock calls.
    """

    def extract_keywords(
        self,
        title: str,
        content: str,
        category: str = "",
        month: str = ""
    ) -> str:
        """Extract a comma-separated list of unique keywords from title, content, category, and month."""
        combined_text = f"{title} {category} {month}\n{content}"
        detected_keywords: Set[str] = set()

        # 1. Exact & case-insensitive dictionary entity matching
        for entity_type, terms in ENTITY_DICTIONARY.items():
            for term in terms:
                # Word boundary match (case insensitive)
                pattern = r"\b" + re.escape(term) + r"\b"
                if re.search(pattern, combined_text, re.IGNORECASE):
                    # Preserve canonical casing from dictionary
                    detected_keywords.add(term)

        # 2. Extract capitalized acronyms (e.g. EC2, RDS, DMS, S3, IAM, ALB, VPC)
        acronyms = re.findall(r"\b[A-Z0-9]{2,6}\b", combined_text)
        for acr in acronyms:
            if acr.lower() not in STOP_WORDS and len(acr) >= 2:
                detected_keywords.add(acr)

        # 3. Extract CamelCase terms (e.g. SafeStart, AccuTrain, AutoScaling)
        camel_terms = re.findall(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b", combined_text)
        for ct in camel_terms:
            detected_keywords.add(ct)

        # 4. Fallback/supplementary token frequency if no dictionary terms matched
        if len(detected_keywords) < 2:
            words = re.findall(r"\b[a-zA-Z]{4,}\b", title.lower())
            for w in words:
                if w not in STOP_WORDS:
                    detected_keywords.add(w.capitalize())

        # Sort keywords for deterministic ordering (dictionary terms first, then alphabetical)
        sorted_keywords = sorted(list(detected_keywords), key=lambda k: (0 if any(k in terms for terms in ENTITY_DICTIONARY.values()) else 1, k.lower()))
        
        return ", ".join(sorted_keywords)
