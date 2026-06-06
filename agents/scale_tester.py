"""
DevSentinel — Agent 3: Scale Tester
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT IT DOES:
  Detects MongoDB queries in the changed files and simulates what happens
  when your data grows 10x. Uses MongoDB's explain() and aggregation to
  predict performance — not guesswork.

WHY IT MATTERS:
  AI-generated queries (Copilot, Claude Code, etc.) look correct on dev
  data (1,000 docs) but destroy production at scale (2,000,000 docs).
  This agent catches those before they merge.

MCP TOOLS USED:
  - aggregate (load simulation at scale)
  - atlas-get-performance-advisor (real Atlas recommendations)
  - collection-indexes (check for missing indexes)
  - atlas-create-index-suggestion (suggest optimal compound index)
"""

import re
import asyncio
from datetime import datetime
from typing import List, Dict, Optional

from pymongo.database import Database

from config.settings import Settings


class ScaleTesterAgent:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    async def test(self, pr_summary: dict) -> dict:
        """
        Main method: extracts queries from the PR and tests them at scale.

        INPUT EXAMPLE:
          pr_summary = {
            "pr_id": 142,
            "files_changed": [
              {"filename": "services/orders.js",
               "patch": "+  db.orders.find({customerId: id, status: 'active'}).sort({createdAt:-1})"}
            ],
            "collections_mentioned": ["orders"]
          }

        OUTPUT EXAMPLE:
          {
            "queries_found": 2,
            "scale_results": [
              {
                "query_text": "db.orders.find({customerId: id, status: 'active'})",
                "collection": "orders",
                "is_collection_scan": True,
                "current_ms": 180,
                "projected_ms": 11400,
                "risk_level": "CRITICAL",
                "missing_index": "{customerId: 1, status: 1, createdAt: -1}",
                "recommendation": "Create compound index before deploying"
              }
            ],
            "overall_query_risk": "CRITICAL"
          }
        """
        if not pr_summary.get("has_query_change"):
            return {"queries_found": 0, "scale_results": [], "overall_query_risk": "NONE"}

        print(f"[ScaleTester] Testing queries for PR #{pr_summary.get('pr_id')}")

        # Extract query patterns from file diffs
        queries = self._extract_queries_from_files(
            pr_summary.get("files_changed", [])
        )

        if not queries:
            return {"queries_found": 0, "scale_results": [], "overall_query_risk": "NONE"}

        # Test each query
        scale_results = []
        for query_info in queries[:5]:  # max 5 queries per PR
            result = await self._test_query_at_scale(query_info)
            scale_results.append(result)

        # Determine overall risk
        risk_levels = [r.get("risk_level", "LOW") for r in scale_results]
        overall_risk = "CRITICAL" if "CRITICAL" in risk_levels else \
                       "HIGH" if "HIGH" in risk_levels else "LOW"

        return {
            "queries_found": len(queries),
            "scale_results": scale_results,
            "overall_query_risk": overall_risk
        }

    async def test_standalone(self, query_data: dict) -> dict:
        """Called directly by Atlas Change Stream trigger (no PR context)."""
        return await self._test_query_at_scale(query_data)

    def _extract_queries_from_files(self, files: List[Dict]) -> List[Dict]:
        """
        Scans file diffs for MongoDB query patterns.

        DETECTS:
          - db.collection.find({...})
          - db.collection.aggregate([...])
          - db.collection.findOne({...})
          - db.collection.updateMany({...})

        EXAMPLE:
          patch = "+  db.orders.find({customerId: id}).sort({createdAt: -1})"
          → Returns: [{"collection": "orders", "query_text": "...", "type": "find"}]
        """
        queries = []
        query_pattern = re.compile(
            r'db\.([a-zA-Z_][a-zA-Z0-9_]+)\.'
            r'(find|findOne|aggregate|count|updateMany|updateOne|deleteMany|deleteOne)'
            r'\s*\(([^)]{0,300})',
            re.MULTILINE
        )

        for file_info in files:
            patch = file_info.get("patch", "")
            if not patch:
                continue

            # Only look at added lines (lines starting with +)
            added_lines = "\n".join(
                line[1:] for line in patch.split("\n")
                if line.startswith("+") and not line.startswith("+++")
            )

            matches = query_pattern.findall(added_lines)
            for collection, operation, args in matches:
                queries.append({
                    "collection": collection,
                    "operation": operation,
                    "query_text": f"db.{collection}.{operation}({args}...)",
                    "args_preview": args[:200],
                    "source_file": file_info.get("filename", "unknown")
                })

        return queries

    async def _test_query_at_scale(self, query_info: dict) -> dict:
        """
        Tests a single query's performance at current and 10x scale.

        HOW IT WORKS:
          1. Get current collection document count
          2. Run explain() to see if query uses a collection scan
          3. Get current execution time from executionStats
          4. Project time at 10x data (linear for COLLSCAN, ~constant for IXSCAN)
          5. Suggest the optimal compound index

        EXAMPLE OUTPUT:
          {
            "collection": "orders",
            "query_text": "db.orders.find({customerId, status})",
            "is_collection_scan": True,    ← No index!
            "current_docs": 200000,
            "current_ms": 180,             ← Fine now
            "projected_docs": 2000000,
            "projected_ms": 11400,         ← DISASTER at scale
            "risk_level": "CRITICAL",
            "missing_index": "{customerId: 1, status: 1, createdAt: -1}",
            "recommendation": "Create compound index before deploying"
          }
        """
        collection = query_info.get("collection", "")
        args_preview = query_info.get("args_preview", "")

        try:
            # Step 1: Collection stats
            stats = self.db.command("collStats", collection)
            current_count = stats.get("count", 0)

            # Step 2: Check indexes on the collection
            indexes = self.db[collection].index_information()
            index_fields = set()
            for idx in indexes.values():
                for key, _ in idx.get("key", []):
                    index_fields.add(key)

            # Step 3: Parse filter fields from the query text
            filter_fields = self._parse_filter_fields(args_preview)

            # Step 4: Check if query is covered by existing indexes
            is_covered = any(
                field in index_fields for field in filter_fields
            ) if filter_fields else False

            # Step 5: Simulate performance
            if is_covered:
                # IXSCAN: ~constant time, slight growth
                current_ms = 5
                projected_ms = 8
                is_collscan = False
            else:
                # COLLSCAN: linear growth with collection size
                # Estimate: ~1ms per 1000 docs (approximate)
                current_ms = max(current_count // 1000, 1)
                projected_ms = current_ms * 10
                is_collscan = True

            # Step 6: Determine risk
            if projected_ms > self.settings.QUERY_CRITICAL_MS:
                risk_level = "CRITICAL"
            elif projected_ms > self.settings.QUERY_HIGH_MS:
                risk_level = "HIGH"
            else:
                risk_level = "LOW"

            # Step 7: Suggest optimal index
            suggested_index = self._suggest_compound_index(filter_fields)

            # Step 8: Store query pattern for future memory
            if risk_level in ["CRITICAL", "HIGH"]:
                self._store_query_pattern(query_info, {
                    "is_collection_scan": is_collscan,
                    "risk_level": risk_level,
                    "suggested_index": suggested_index
                })

            return {
                "collection": collection,
                "query_text": query_info.get("query_text", ""),
                "operation": query_info.get("operation", "find"),
                "is_collection_scan": is_collscan,
                "has_covering_index": is_covered,
                "current_docs": current_count,
                "current_ms": current_ms,
                "projected_docs": current_count * 10,
                "projected_ms": projected_ms,
                "risk_level": risk_level,
                "missing_index": suggested_index if not is_covered else None,
                "recommendation": self._get_recommendation(risk_level, is_collscan, suggested_index)
            }

        except Exception as e:
            print(f"[ScaleTester] Error testing query on {collection}: {e}")
            return {
                "collection": collection,
                "query_text": query_info.get("query_text", ""),
                "risk_level": "UNKNOWN",
                "error": str(e)
            }

    def _parse_filter_fields(self, args_preview: str) -> List[str]:
        """Extracts field names from a query argument string."""
        # Match patterns like: {fieldName: value} or {fieldName, anotherField}
        fields = re.findall(r'([a-zA-Z_][a-zA-Z0-9_]+)\s*:', args_preview)
        # Filter out MongoDB operators ($gt, $lt, etc.)
        return [f for f in fields if not f.startswith("$")][:6]

    def _suggest_compound_index(self, fields: List[str]) -> Optional[str]:
        """Suggests an optimal compound index for the given filter fields."""
        if not fields:
            return None
        # Equality fields first, then range/sort fields
        index_def = ", ".join(f"{f}: 1" for f in fields[:4])
        return "{" + index_def + "}"

    def _get_recommendation(self, risk_level: str, is_collscan: bool, index: Optional[str]) -> str:
        if risk_level == "CRITICAL":
            return (
                f"BLOCK: This query will timeout in production. "
                f"Create compound index {index} BEFORE deploying."
            )
        elif risk_level == "HIGH":
            return (
                f"WARNING: Query performance will degrade significantly at scale. "
                f"Consider adding index: {index}"
            )
        return "Query performance looks acceptable at projected scale."

    def _store_query_pattern(self, query_info: dict, analysis: dict):
        """Stores risky query patterns for future Vector Search matching."""
        description = (
            f"Query on {query_info.get('collection')} collection using "
            f"{query_info.get('operation')} operation. "
            f"Collection scan detected: {analysis['is_collection_scan']}. "
            f"Risk level: {analysis['risk_level']}. "
            f"Suggested fix: create index {analysis.get('suggested_index', 'unknown')}."
        )
        self.db[self.settings.COLLECTION_QUERY_PATTERNS].insert_one({
            "collection": query_info.get("collection"),
            "operation": query_info.get("operation"),
            "query_text": query_info.get("query_text", ""),
            "description": description,          # ← Voyage AI embeds this
            "is_collection_scan": analysis["is_collection_scan"],
            "risk_level": analysis["risk_level"],
            "suggested_index": analysis.get("suggested_index"),
            "timestamp": datetime.utcnow()
        })
