"""
DevSentinel — Agent 2: Analyst
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT IT DOES:
  Searches the team's incident history using Atlas Vector Search to find
  past failures similar to the current PR. Then calculates a confidence
  score using a real MongoDB aggregation pipeline.

WHY IT MATTERS:
  This is the "memory" layer. When a developer opens a PR that renames
  a field, this agent finds that your team did something similar 3 months
  ago and it caused a 6-hour outage.

MCP TOOLS USED:
  - Atlas Vector Search (semantic incident matching)
  - find (retrieve full incident documents)
  - aggregate (confidence scoring formula)
  - collection-indexes (check for active indexes on changed fields)
"""

import asyncio
from datetime import datetime
from typing import List, Dict, Any

from pymongo.database import Database

from config.settings import Settings
from tools.embedding_tool import get_embedding


class AnalystAgent:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    async def analyse(self, pr_summary: dict) -> dict:
        """
        Main analysis method. Runs Vector Search + confidence scoring.

        INPUT EXAMPLE:
          pr_summary = {
            "pr_id": 142,
            "description": "PR renames payment_status field in orders collection...",
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
                "title": "Payment Status Rename Cascade Failure",
                "similarity_score": 0.94,
                "date": "2026-03-03",
                "recovery_time_hours": 6,
                "fix_applied": "Dual-write migration",
                "evidence": "Same collection, same field rename pattern"
              }
            ],
            "index_warnings": ["payment_status has active index — rebuild required"],
            "affected_collections": ["orders", "refunds", "analytics"],
            "confidence_breakdown": {
              "reference_count": 847,
              "criticality": 1.0,
              "similarity_bonus": 0.15
            }
          }
        """
        print(f"[Analyst] Analysing PR #{pr_summary.get('pr_id')}")

        # Run all analysis tasks in parallel
        similar_incidents, index_warnings = await asyncio.gather(
            self._search_similar_incidents(pr_summary["description"]),
            self._check_indexes(pr_summary.get("mongo_fields_changed", []),
                               pr_summary.get("collections_mentioned", []))
        )

        # Calculate confidence score from real data
        confidence_data = await self._calculate_confidence(
            pr_summary.get("mongo_fields_changed", []),
            pr_summary.get("collections_mentioned", []),
            similar_incidents
        )

        risk_score = confidence_data["confidence"]
        risk_level = self._get_risk_level(risk_score)

        # Update the PR analysis document in MongoDB
        self.db[self.settings.COLLECTION_PR_ANALYSES].update_one(
            {"pr_id": pr_summary["pr_id"]},
            {"$set": {
                "risk_score": risk_score,
                "risk_level": risk_level,
                "matched_incidents": [
                    {k: v for k, v in inc.items() if k != "_id"}
                    for inc in similar_incidents
                ],
                "index_warnings": index_warnings,
                "analysis_timestamp": datetime.utcnow(),
                "status": "analysed"
            }}
        )

        return {
            "risk_score": risk_score,
            "risk_level": risk_level,
            "matched_incidents": similar_incidents,
            "index_warnings": index_warnings,
            "affected_collections": confidence_data.get("affected_collections", []),
            "confidence_breakdown": confidence_data
        }

    async def _search_similar_incidents(self, description: str) -> List[Dict]:
        """
        Uses Atlas Vector Search to find past incidents semantically similar
        to the current PR description.

        HOW IT WORKS:
          1. Generate Voyage AI embedding for the PR description
          2. Run $vectorSearch against past_incidents collection
          3. Return top 5 incidents with similarity score > 0.75

        EXAMPLE QUERY:
          Input:  "PR renames payment_status in orders collection"
          Output: Finds "Payment Status Rename Cascade Failure" (score: 0.94)
                  even though exact words don't match perfectly.

        This is semantic understanding — NOT keyword search.
        """
        try:
            # Get embedding for the PR description
            embedding = await get_embedding(description)

            pipeline = [
                {
                    "$vectorSearch": {
                        "index": self.settings.INCIDENT_VECTOR_INDEX,
                        "path": "embedding",
                        "queryVector": embedding,
                        "numCandidates": self.settings.VECTOR_NUM_CANDIDATES,
                        "limit": self.settings.VECTOR_RESULT_LIMIT
                    }
                },
                {
                    "$project": {
                        "title": 1,
                        "description": 1,
                        "field_changed": 1,
                        "collections_affected": 1,
                        "services_affected": 1,
                        "fix_applied": 1,
                        "recovery_time_hours": 1,
                        "severity": 1,
                        "date": 1,
                        "score": {"$meta": "vectorSearchScore"}
                    }
                },
                {
                    # Only return high-confidence matches
                    "$match": {
                        "score": {"$gt": self.settings.VECTOR_SIMILARITY_THRESHOLD}
                    }
                },
                {
                    "$sort": {"score": -1}
                }
            ]

            results = list(
                self.db[self.settings.COLLECTION_PAST_INCIDENTS].aggregate(pipeline)
            )

            print(f"[Analyst] Vector Search found {len(results)} similar incidents")
            return results

        except Exception as e:
            print(f"[Analyst] Vector Search error: {e}")
            return []

    async def _check_indexes(self, fields: List[str], collections: List[str]) -> List[str]:
        """
        Checks if any of the changed fields have active MongoDB indexes.
        If yes, flags that an index rebuild will be required.

        EXAMPLE:
          fields = ["payment_status"]
          collections = ["orders"]
          → Finds index: {payment_status: 1} on orders collection
          → Returns: ["WARNING: payment_status has active index on orders —
                       index rebuild required after rename"]
        """
        warnings = []
        for collection in collections:
            try:
                indexes = self.db[collection].index_information()
                for index_name, index_info in indexes.items():
                    index_keys = [k[0] for k in index_info.get("key", [])]
                    for field in fields:
                        if field in index_keys:
                            warnings.append(
                                f"WARNING: '{field}' has active index '{index_name}' "
                                f"on '{collection}' collection — "
                                f"index rebuild required after rename"
                            )
            except Exception as e:
                print(f"[Analyst] Index check error for {collection}: {e}")

        return warnings

    async def _calculate_confidence(
        self, fields: List[str], collections: List[str], similar_incidents: List[Dict]
    ) -> dict:
        """
        Calculates a real confidence score using MongoDB aggregation.
        NOT guessed by the LLM — derived from actual data.

        FORMULA:
          reference_score = min(reference_count / 1000, 1.0)
          criticality     = lookup table (orders=1.0, payments=1.0, refunds=0.95, ...)
          similarity_bonus = top_similarity_score × 0.2
          final_confidence = (reference_score × criticality) + similarity_bonus

        EXAMPLE:
          orders.payment_status has 847 references
          reference_score = min(847/1000, 1.0) = 0.847
          criticality     = 1.0 (orders is critical)
          similarity_bonus = 0.94 × 0.2 = 0.188 (from Vector Search)
          confidence      = min(0.847 + 0.188, 1.0) = 1.0 → capped at 0.95
        """
        if not fields or not collections:
            return {"confidence": 0.5, "reference_count": 0, "criticality": 0.5}

        target_collection = collections[0]
        target_field = fields[0] if fields else ""

        try:
            pipeline = [
                {"$match": {target_field: {"$exists": True}}},
                {"$count": "reference_count"},
                {
                    "$addFields": {
                        "criticality": {
                            "$switch": {
                                "branches": [
                                    {"case": {"$eq": [target_collection, "orders"]},   "then": 1.0},
                                    {"case": {"$eq": [target_collection, "payments"]}, "then": 1.0},
                                    {"case": {"$eq": [target_collection, "refunds"]},  "then": 0.95},
                                    {"case": {"$eq": [target_collection, "users"]},    "then": 0.90},
                                    {"case": {"$eq": [target_collection, "sessions"]}, "then": 0.85},
                                    {"case": {"$eq": [target_collection, "analytics"]},"then": 0.70},
                                ],
                                "default": 0.60
                            }
                        }
                    }
                },
                {
                    "$addFields": {
                        "ref_score": {
                            "$min": [{"$divide": ["$reference_count", 1000]}, 1.0]
                        }
                    }
                },
                {
                    "$addFields": {
                        "base_confidence": {"$multiply": ["$ref_score", "$criticality"]}
                    }
                }
            ]

            result = list(self.db[target_collection].aggregate(pipeline))

            if not result:
                base_conf = 0.5
                ref_count = 0
                criticality = 0.5
            else:
                base_conf = result[0].get("base_confidence", 0.5)
                ref_count = result[0].get("reference_count", 0)
                criticality = result[0].get("criticality", 0.5)

            # Add similarity bonus from Vector Search
            similarity_bonus = 0.0
            if similar_incidents:
                top_score = similar_incidents[0].get("score", 0)
                similarity_bonus = top_score * 0.2  # max 20% bonus

            final_confidence = min(base_conf + similarity_bonus, 0.97)

            return {
                "confidence": round(final_confidence, 2),
                "reference_count": ref_count,
                "criticality": criticality,
                "similarity_bonus": round(similarity_bonus, 3),
                "affected_collections": collections
            }

        except Exception as e:
            print(f"[Analyst] Confidence calculation error: {e}")
            # Fallback: use similarity score alone
            top_score = similar_incidents[0].get("score", 0.5) if similar_incidents else 0.5
            return {"confidence": round(top_score * 0.9, 2), "reference_count": 0}

    def _get_risk_level(self, score: float) -> str:
        if score >= self.settings.CONFIDENCE_HIGH_THRESHOLD:
            return "CRITICAL"
        elif score >= self.settings.CONFIDENCE_MED_THRESHOLD:
            return "HIGH"
        else:
            return "LOW"
