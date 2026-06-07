"""
DevSentinel — Agent 2: Analyst
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT IT DOES:
  Searches MongoDB Atlas for past incidents similar to the current PR.
  Uses Vector Search (Voyage AI embeddings) to find the closest historical
  incidents, then calculates a confidence score based on similarity,
  collection criticality, and reference count.

WHY IT MATTERS:
  Production databases have a memory — past incidents document exactly
  what broke and why. Vector Search connects new PRs to that institutional
  knowledge, so we don't repeat the same mistakes.

MCP TOOLS USED:
  - Vector Search (past_incidents collection)
  - aggregate (confidence scoring)
  - collection-indexes (check for index conflicts)
"""

import re
import asyncio
from datetime import datetime
from typing import List, Dict, Optional

import voyageai
from pymongo.database import Database

from config.settings import Settings


class AnalystAgent:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        try:
            self.voyage = voyageai.Client(api_key=settings.VOYAGE_API_KEY)
        except Exception:
            self.voyage = None

    async def analyse(self, pr_summary: dict) -> dict:
        """
        Main method: searches for similar past incidents and assesses risk.

        INPUT EXAMPLE:
          pr_summary = {
            "pr_id": 142,
            "pr_title": "Rename payment_status to payment_state",
            "description": "PR 142 ... affects payment_status in orders collection...",
            "mongo_fields_changed": ["payment_status"],
            "collections_mentioned": ["orders"],
            "has_schema_change": True
          }

        OUTPUT EXAMPLE:
          {
            "risk_score": 0.91,
            "risk_level": "CRITICAL",
            "matched_incidents": [
              {
                "title": "Payment Status Field Rename Cascade Failure",
                "score": 0.94,
                "recovery_time_hours": 6
              }
            ],
            "index_warnings": ["WARNING: 'payment_status' has active index..."],
            "affected_collections": ["orders"],
            "confidence_breakdown": {...}
          }
        """
        print(f"[Analyst] Analysing PR #{pr_summary.get('pr_id')}: {pr_summary.get('pr_title')}")

        description = pr_summary.get("description", pr_summary.get("pr_title", ""))
        fields_changed = pr_summary.get("mongo_fields_changed", [])
        collections = pr_summary.get("collections_mentioned", [])

        # Step 1: Vector search for similar past incidents
        matched_incidents = await self._vector_search_incidents(description)

        # Step 2: Check indexes for changed fields/collections
        index_warnings = self._check_indexes(fields_changed, collections)

        # Step 3: Calculate confidence / risk score
        confidence = self._calculate_confidence(
            matched_incidents, pr_summary
        )

        risk_level = self._get_risk_level(confidence)

        return {
            "risk_score": confidence,
            "risk_level": risk_level,
            "matched_incidents": matched_incidents,
            "index_warnings": index_warnings,
            "affected_collections": collections,
            "confidence_breakdown": {
                "confidence": confidence,
                "reference_count": sum(
                    i.get("reference_count", 0) for i in matched_incidents
                ),
                "criticality": 1.0 if any(
                    c in ["orders", "payments", "users"] for c in collections
                ) else 0.5,
                "similarity_bonus": max(
                    (i.get("score", 0) - 0.75) for i in matched_incidents
                ) if matched_incidents else 0,
            },
        }

    async def _vector_search_incidents(self, description: str) -> List[Dict]:
        """
        Uses Voyage AI to embed the PR description, then searches the
        past_incidents collection via MongoDB Atlas Vector Search.

        EXAMPLE MATCH:
          PR: "rename payment_status field in orders"
          → Matches: "Payment Status Rename Cascade Failure (score: 0.94)"
        """
        try:
            # Generate embedding for the PR description
            if self.voyage:
                embedding = self.voyage.embed(
                    [description],
                    model="voyage-3",
                    input_type="query"
                ).embeddings[0]
            else:
                raise ValueError("Voyage client not available")

            # Atlas Vector Search pipeline
            pipeline = [
                {
                    "$vectorSearch": {
                        "index": self.settings.INCIDENT_VECTOR_INDEX,
                        "path": "description_embedding",
                        "queryVector": embedding,
                        "numCandidates": self.settings.VECTOR_NUM_CANDIDATES,
                        "limit": self.settings.VECTOR_RESULT_LIMIT,
                    }
                },
                {
                    "$project": {
                        "title": 1,
                        "description": 1,
                        "field_changed": 1,
                        "collections_affected": 1,
                        "fix_applied": 1,
                        "recovery_time_hours": 1,
                        "severity": 1,
                        "date": 1,
                        "reference_count": 1,
                        "score": {"$meta": "vectorSearchScore"},
                    }
                },
                {
                    "$match": {
                        "score": {"$gte": self.settings.VECTOR_SIMILARITY_THRESHOLD}
                    }
                },
            ]

            results = list(
                self.db[self.settings.COLLECTION_PAST_INCIDENTS].aggregate(pipeline)
            )
            return results

        except Exception as e:
            print(f"[Analyst] Vector search error: {e}")
            return []

    def _check_indexes(self, fields_changed: List[str], collections: List[str]) -> List[str]:
        """
        Checks if any of the changed fields have active MongoDB indexes.
        If a field is renamed and it has an index, that index will break.

        EXAMPLE WARNING:
          "WARNING: 'payment_status' has active index 'payment_status_1'
           on 'orders' collection — index rebuild required after rename"
        """
        warnings = []
        for collection in collections:
            try:
                indexes = self.db[collection].index_information()
                for idx_name, idx_info in indexes.items():
                    if idx_name == "_id_":
                        continue
                    idx_keys = [k for k, _ in idx_info.get("key", [])]
                    for field in fields_changed:
                        if field in idx_keys:
                            warnings.append(
                                f"WARNING: '{field}' has active index '{idx_name}' "
                                f"on '{collection}' collection — index rebuild required after rename"
                            )
            except Exception as e:
                print(f"[Analyst] Could not check indexes for {collection}: {e}")
        return warnings

    def _calculate_confidence(self, incidents: List[Dict], pr_summary: dict) -> float:
        """
        Calculates a composite risk confidence score from:
          - Vector similarity of matched incidents
          - Collection criticality (orders/payments = high)
          - PR risk keywords
          - Reference count (how often the pattern has occurred)

        SCORE RANGES:
          >= 0.80 → CRITICAL
          >= 0.50 → HIGH
          < 0.50  → LOW
        """
        if not incidents:
            # Base risk from keyword signals only
            base = 0.3 if pr_summary.get("has_schema_change") else 0.1
            base += 0.1 if pr_summary.get("has_query_change") else 0
            return min(base, 0.49)

        top_incident = incidents[0]
        similarity = top_incident.get("score", 0)

        # Collection criticality boost
        critical_collections = {"orders", "payments", "users", "accounts", "transactions"}
        collections = set(pr_summary.get("collections_mentioned", []))
        criticality = 1.0 if collections & critical_collections else 0.7

        # Reference count boost (more historical occurrences = more dangerous)
        ref_count = top_incident.get("reference_count", 0)
        ref_boost = min(ref_count / 1000, 0.2)  # max 0.2 boost

        confidence = similarity * criticality + ref_boost
        return min(round(confidence, 3), 1.0)

    def _get_risk_level(self, confidence: float) -> str:
        """Maps a confidence score to a risk level label."""
        if confidence >= self.settings.CONFIDENCE_HIGH_THRESHOLD:
            return "CRITICAL"
        elif confidence >= self.settings.CONFIDENCE_MED_THRESHOLD:
            return "HIGH"
        return "LOW"