"""
DevSentinel — Test Suite
━━━━━━━━━━━━━━━━━━━━━━━━
Tests for the 5-agent pipeline, signature verification, and settings.
Run with: pytest tests/ -v
"""

import os
import sys
import hmac
import hashlib
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set minimal env vars for testing
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("GEMINI_API_KEY", "test_key")
os.environ.setdefault("GITHUB_TOKEN", "test_token")
os.environ.setdefault("VOYAGE_API_KEY", "test_voyage")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test_secret")

from config.settings import Settings
from main import verify_github_signature


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SETTINGS TESTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestSettings:
    def test_settings_reads_env_vars(self):
        """Settings should read env vars in __post_init__."""
        # Force-override env vars AFTER .env may have been loaded by main.py import
        import os
        os.environ["MONGODB_URI"] = "mongodb://localhost:27017"
        os.environ["GEMINI_API_KEY"] = "test_key"
        os.environ["GITHUB_TOKEN"] = "test_token"
        s = Settings()
        assert s.MONGODB_URI == "mongodb://localhost:27017"
        assert s.GEMINI_API_KEY == "test_key"
        assert s.GITHUB_TOKEN == "test_token"

    def test_settings_defaults(self):
        """Settings should have correct default values."""
        s = Settings()
        assert s.GEMINI_MODEL == "gemini-2.5-flash"
        assert s.VECTOR_SIMILARITY_THRESHOLD == 0.75
        assert s.VECTOR_NUM_CANDIDATES == 100
        assert s.CONFIDENCE_HIGH_THRESHOLD == 0.80
        assert s.QUERY_CRITICAL_MS == 5000
        assert s.AUTO_POST_COMMENT is True
        assert s.AUTO_CREATE_FIX_PR is False

    def test_collection_names(self):
        """Collection names should be correct."""
        s = Settings()
        assert s.COLLECTION_PAST_INCIDENTS == "past_incidents"
        assert s.COLLECTION_PR_ANALYSES == "pr_analyses"
        assert s.COLLECTION_QUERY_PATTERNS == "query_patterns"
        assert s.COLLECTION_AUDIT_LOG == "audit_log"
        assert s.COLLECTION_CHANGE_REQUESTS == "change_requests"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# WEBHOOK SIGNATURE TESTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestWebhookSignature:
    """Test HMAC-SHA256 signature verification."""

    SECRET = "my_webhook_secret"

    def _make_sig(self, payload: bytes) -> str:
        mac = hmac.new(self.SECRET.encode(), payload, hashlib.sha256)
        return "sha256=" + mac.hexdigest()

    def test_valid_signature(self):
        payload = b'{"action": "opened"}'
        sig = self._make_sig(payload)
        assert verify_github_signature(payload, sig, self.SECRET) is True

    def test_invalid_signature(self):
        payload = b'{"action": "opened"}'
        assert verify_github_signature(payload, "sha256=invalid", self.SECRET) is False

    def test_empty_signature(self):
        payload = b'{"action": "opened"}'
        assert verify_github_signature(payload, "", self.SECRET) is False

    def test_wrong_secret(self):
        payload = b'{"action": "opened"}'
        sig = self._make_sig(payload)
        assert verify_github_signature(payload, sig, "wrong_secret") is False

    def test_no_secret_configured(self):
        payload = b'{"action": "opened"}'
        sig = self._make_sig(payload)
        assert verify_github_signature(payload, sig, "") is False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HARVESTER AGENT TESTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestHarvesterAgent:
    """Tests for signal extraction logic (no DB/GitHub required)."""

    @pytest.fixture
    def harvester(self):
        from agents.harvester import HarvesterAgent
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=MagicMock())
        settings = Settings()
        return HarvesterAgent(mock_db, settings)

    def test_extract_mongo_signals_rename(self, harvester):
        signals = harvester._extract_mongo_signals(
            title="Rename payment_status to payment_state in orders",
            body="This standardises field naming",
            files=[]
        )
        assert signals["has_schema_change"] is True
        assert "rename" in signals["keywords"]

    def test_extract_mongo_signals_query_change(self, harvester):
        signals = harvester._extract_mongo_signals(
            title="Add new aggregation pipeline for orders",
            body="Uses $match, $group and $sort stages",
            files=[{"filename": "orders.js", "patch": "+db.orders.aggregate([{$match:...}])"}]
        )
        assert signals["has_query_change"] is True

    def test_extract_mongo_signals_no_mongo(self, harvester):
        signals = harvester._extract_mongo_signals(
            title="Update README with deployment instructions",
            body="Adds Cloud Run deployment steps",
            files=[]
        )
        assert signals["has_schema_change"] is False
        assert signals["has_query_change"] is False

    def test_build_description_includes_pr_number(self, harvester):
        pr_data = {
            "number": 42,
            "title": "Rename payment_status",
            "user": {"login": "dev"},
            "html_url": "https://github.com/org/repo/pull/42",
            "head": {"ref": "feature/rename", "sha": "abc123"},
        }
        files = [{"filename": "orders.js", "status": "modified",
                  "additions": 5, "deletions": 3, "patch": ""}]
        signals = {"has_schema_change": True, "has_query_change": False,
                   "fields": ["payment_status"], "collections": ["orders"],
                   "keywords": ["rename", "field"]}
        desc = harvester._build_description(pr_data, files, signals)
        assert "PR 42" in desc
        assert "Rename payment_status" in desc


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SCALE TESTER TESTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestScaleTester:
    """Tests for query extraction and risk classification."""

    @pytest.fixture
    def scale_tester(self):
        from agents.scale_tester import ScaleTesterAgent
        mock_db = MagicMock()
        settings = Settings()
        return ScaleTesterAgent(mock_db, settings)

    def test_extract_queries_finds_find_call(self, scale_tester):
        files = [{
            "filename": "orders.js",
            "patch": "+  db.orders.find({customerId: id, status: 'active'})"
        }]
        queries = scale_tester._extract_queries_from_files(files)
        assert len(queries) == 1
        assert queries[0]["collection"] == "orders"
        assert queries[0]["operation"] == "find"

    def test_extract_queries_finds_aggregate(self, scale_tester):
        files = [{
            "filename": "reports.js",
            "patch": "+  db.transactions.aggregate([{$match: {status: 'paid'}}])"
        }]
        queries = scale_tester._extract_queries_from_files(files)
        assert len(queries) == 1
        assert queries[0]["collection"] == "transactions"
        assert queries[0]["operation"] == "aggregate"

    def test_extract_queries_skips_deleted_lines(self, scale_tester):
        files = [{
            "filename": "orders.js",
            "patch": "-  db.orders.find({old: 'query'})"  # deleted line
        }]
        queries = scale_tester._extract_queries_from_files(files)
        assert len(queries) == 0

    def test_parse_filter_fields(self, scale_tester):
        args = "{customerId: id, status: 'active', createdAt: {$gte: date}}"
        fields = scale_tester._parse_filter_fields(args)
        assert "customerId" in fields
        assert "status" in fields
        assert "$gte" not in fields  # operators filtered out

    def test_suggest_compound_index(self, scale_tester):
        fields = ["customerId", "status", "createdAt"]
        idx = scale_tester._suggest_compound_index(fields)
        assert "customerId" in idx
        assert "status" in idx

    def test_risk_level_critical(self, scale_tester):
        settings = Settings()
        # projected_ms > QUERY_CRITICAL_MS (5000) → CRITICAL
        projected_ms = 11400
        if projected_ms > settings.QUERY_CRITICAL_MS:
            risk = "CRITICAL"
        elif projected_ms > settings.QUERY_HIGH_MS:
            risk = "HIGH"
        else:
            risk = "LOW"
        assert risk == "CRITICAL"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ANALYST AGENT TESTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestAnalystAgent:
    """Tests for risk level classification."""

    @pytest.fixture
    def analyst(self):
        from agents.analyst import AnalystAgent
        mock_db = MagicMock()
        settings = Settings()
        return AnalystAgent(mock_db, settings)

    def test_risk_level_critical(self, analyst):
        assert analyst._get_risk_level(0.95) == "CRITICAL"
        assert analyst._get_risk_level(0.80) == "CRITICAL"

    def test_risk_level_high(self, analyst):
        assert analyst._get_risk_level(0.75) == "HIGH"
        assert analyst._get_risk_level(0.50) == "HIGH"

    def test_risk_level_low(self, analyst):
        assert analyst._get_risk_level(0.49) == "LOW"
        assert analyst._get_risk_level(0.10) == "LOW"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RISK NARRATOR TESTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestRiskNarrator:
    """Tests for fallback comment generation (no Gemini call needed)."""

    @pytest.fixture
    def narrator(self):
        from agents.risk_narrator import RiskNarratorAgent
        settings = Settings()
        with patch("google.generativeai.configure"):
            with patch("google.generativeai.GenerativeModel"):
                return RiskNarratorAgent(settings)

    def test_fallback_comment_critical(self, narrator):
        pr_summary = {"pr_id": 42, "pr_title": "Rename payment_status",
                      "pr_author": "dev", "files_changed": []}
        comment = narrator._fallback_comment(pr_summary, 0.91, "CRITICAL", [], [])
        assert "🔴" in comment
        assert "CRITICAL" in comment
        assert "PR #42" in comment
        assert "DevSentinel" in comment

    def test_fallback_comment_high(self, narrator):
        pr_summary = {"pr_id": 10, "pr_title": "Add new index",
                      "pr_author": "dev", "files_changed": []}
        comment = narrator._fallback_comment(pr_summary, 0.65, "HIGH", [], [])
        assert "🟡" in comment
        assert "HIGH" in comment

    def test_fallback_comment_low(self, narrator):
        pr_summary = {"pr_id": 5, "pr_title": "Fix typo in README",
                      "pr_author": "dev", "files_changed": []}
        comment = narrator._fallback_comment(pr_summary, 0.2, "LOW", [], [])
        assert "🟢" in comment


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FASTAPI ENDPOINT TESTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestFastAPIEndpoints:
    """Integration tests for FastAPI endpoints (no DB required)."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        import main
        # Patch get_db and ping so lifespan initialises main.db and main.settings correctly
        with patch("main.get_db", return_value=MagicMock()), \
             patch("main.ping", return_value=True):
            with TestClient(main.app, raise_server_exceptions=False) as c:
                yield c

    def test_health_endpoint(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "timestamp" in data

    def test_root_endpoint(self, client):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        assert len(data["agents"]) == 5

    def test_webhook_ignores_non_pr_events(self, client):
        import json, hmac as _hmac, hashlib
        import main
        payload = json.dumps({"action": "labeled"}).encode()
        secret = main.settings.GITHUB_WEBHOOK_SECRET or "test_secret"
        sig = "sha256=" + _hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        response = client.post(
            "/webhook/github",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "issues",
                "X-Hub-Signature-256": sig,
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"
