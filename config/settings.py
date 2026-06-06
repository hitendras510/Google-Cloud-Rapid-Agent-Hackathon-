"""
DevSentinel — Settings
All environment variables and configuration in one place.
"""

import os
from dataclasses import dataclass


@dataclass
class Settings:
    # ── MongoDB ───────────────────────────────────────────────────
    MONGODB_URI: str = os.environ.get("MONGODB_URI", "")
    MONGODB_DB_NAME: str = os.environ.get("MONGODB_DB_NAME", "devsentiinel")

    # ── Google / Gemini ───────────────────────────────────────────
    GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # ── GitHub ────────────────────────────────────────────────────
    GITHUB_TOKEN: str = os.environ.get("GITHUB_TOKEN", "")
    GITHUB_WEBHOOK_SECRET: str = os.environ.get("GITHUB_WEBHOOK_SECRET", "")

    # ── Vector Search ─────────────────────────────────────────────
    INCIDENT_VECTOR_INDEX: str = "incident_vector_index"
    QUERY_VECTOR_INDEX: str = "query_vector_index"
    VECTOR_SIMILARITY_THRESHOLD: float = 0.75
    VECTOR_NUM_CANDIDATES: int = 100
    VECTOR_RESULT_LIMIT: int = 5
    EMBEDDING_DIMENSIONS: int = 1024   # Voyage AI default

    # ── Risk Thresholds ───────────────────────────────────────────
    CONFIDENCE_HIGH_THRESHOLD: float = 0.80
    CONFIDENCE_MED_THRESHOLD: float = 0.50
    QUERY_CRITICAL_MS: int = 5000    # >5s = CRITICAL
    QUERY_HIGH_MS: int = 1000        # >1s = HIGH

    # ── Pipeline ──────────────────────────────────────────────────
    PIPELINE_TIMEOUT_SECONDS: int = 60
    AUTO_POST_COMMENT: bool = True   # Set False to require manual confirm
    AUTO_CREATE_FIX_PR: bool = False # Always requires user confirmation

    # ── Collections ───────────────────────────────────────────────
    COLLECTION_PAST_INCIDENTS: str = "past_incidents"
    COLLECTION_PR_ANALYSES: str = "pr_analyses"
    COLLECTION_QUERY_PATTERNS: str = "query_patterns"
    COLLECTION_AUDIT_LOG: str = "audit_log"
    COLLECTION_CHANGE_REQUESTS: str = "change_requests"
