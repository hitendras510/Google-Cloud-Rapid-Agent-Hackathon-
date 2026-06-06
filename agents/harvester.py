"""
DevSentinel — Agent 1: Harvester
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT IT DOES:
  Listens for GitHub PR events and Atlas Change Stream query events.
  Extracts meaningful data from each event, builds a rich text description,
  and stores it in MongoDB Atlas with Voyage AI auto-embeddings.

WHY IT MATTERS:
  Every PR and query stored here becomes searchable memory for Agent 2.
  The richer the description, the better the Vector Search matches.

MCP TOOLS USED:
  - insert-many (with Voyage AI autoEmbed)
  - collection-schema
"""

import asyncio
import re
from datetime import datetime
from typing import Tuple

from github import Github
from pymongo.database import Database

from config.settings import Settings


class HarvesterAgent:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        self.gh = Github(settings.GITHUB_TOKEN)

    async def process_pr(self, pr_data: dict, repo_name: str) -> Tuple[str, dict]:
        """
        Main method: processes a GitHub PR event.

        INPUT EXAMPLE:
          pr_data = {
            "number": 142,
            "title": "Rename payment_status to payment_state in orders collection",
            "body": "This change standardises our field naming convention.",
            "html_url": "https://github.com/myorg/myrepo/pull/142",
            "user": {"login": "developer_name"},
            "head": {"sha": "abc123", "ref": "feature/rename-payment-field"}
          }

        OUTPUT EXAMPLE:
          Returns (doc_id, pr_summary) where pr_summary contains:
          {
            "pr_id": 142,
            "pr_title": "Rename payment_status ...",
            "description": "PR 142 renames payment_status to payment_state ...",
            "mongo_fields_changed": ["payment_status"],
            "files_changed": ["services/checkout.js", "models/order.js"],
            "risk_keywords": ["rename", "payment", "status"],
            "timestamp": datetime(2026, 6, 5, 10, 30),
            "status": "pending_analysis"
          }
        """
        print(f"[Harvester] Processing PR #{pr_data['number']}: {pr_data['title']}")

        # Step 1: Fetch file changes from GitHub
        files_changed = await self._get_changed_files(repo_name, pr_data["number"])

        # Step 2: Extract MongoDB-relevant signals
        mongo_signals = self._extract_mongo_signals(
            pr_data["title"],
            pr_data.get("body", ""),
            files_changed
        )

        # Step 3: Build rich description for Voyage AI embedding
        description = self._build_description(pr_data, files_changed, mongo_signals)

        # Step 4: Assemble the document
        pr_doc = {
            "pr_id": pr_data["number"],
            "pr_title": pr_data["title"],
            "pr_url": pr_data["html_url"],
            "pr_author": pr_data["user"]["login"],
            "pr_branch": pr_data["head"]["ref"],
            "repo": repo_name,
            "description": description,          # ← Voyage AI embeds THIS field
            "files_changed": files_changed,
            "mongo_fields_changed": mongo_signals["fields"],
            "collections_mentioned": mongo_signals["collections"],
            "risk_keywords": mongo_signals["keywords"],
            "has_schema_change": mongo_signals["has_schema_change"],
            "has_query_change": mongo_signals["has_query_change"],
            "timestamp": datetime.utcnow(),
            "status": "pending_analysis",
            "risk_score": None,
            "matched_incidents": [],
        }

        # Step 5: Store in MongoDB (Voyage AI autoEmbed generates the embedding)
        result = self.db[self.settings.COLLECTION_PR_ANALYSES].insert_one(pr_doc)
        doc_id = str(result.inserted_id)

        # Step 6: Write harvest audit log
        self._write_audit_log("pr_harvested", pr_data["number"], {
            "doc_id": doc_id,
            "files_changed_count": len(files_changed),
            "mongo_fields_detected": mongo_signals["fields"]
        })

        print(f"[Harvester] Stored PR #{pr_data['number']} as doc {doc_id}")
        return doc_id, pr_doc

    async def _get_changed_files(self, repo_name: str, pr_number: int) -> list:
        """
        Fetches the list of files changed in the PR from GitHub API.

        EXAMPLE OUTPUT:
        [
          {"filename": "services/checkout.js", "status": "modified",
           "additions": 12, "deletions": 8},
          {"filename": "models/order.js", "status": "modified",
           "additions": 3, "deletions": 3}
        ]
        """
        try:
            repo = self.gh.get_repo(repo_name)
            pr = repo.get_pull(pr_number)
            return [
                {
                    "filename": f.filename,
                    "status": f.status,
                    "additions": f.additions,
                    "deletions": f.deletions,
                    "patch": f.patch[:500] if f.patch else ""  # first 500 chars of diff
                }
                for f in pr.get_files()
            ]
        except Exception as e:
            print(f"[Harvester] Warning: Could not fetch PR files: {e}")
            return []

    def _extract_mongo_signals(self, title: str, body: str, files: list) -> dict:
        """
        Scans PR title, body, and file diffs for MongoDB-relevant signals.

        EXAMPLE:
          title = "Rename payment_status to payment_state"
          → fields = ["payment_status", "payment_state"]
          → collections = ["orders", "payments"]
          → keywords = ["rename", "payment", "status"]
          → has_schema_change = True
        """
        combined_text = f"{title} {body} " + " ".join(
            f.get("filename", "") + " " + f.get("patch", "")
            for f in files
        )
        text_lower = combined_text.lower()

        # Detect field renames
        rename_keywords = ["rename", "renamed", "renaming", "renames"]
        schema_keywords = ["schema", "field", "column", "attribute", "property", "index"]
        query_keywords  = ["find(", "aggregate(", "query", "pipeline", "lookup", "$match",
                           "$group", "$sort", "$project", "createindex"]

        # Extract likely field names (words after "rename", quoted words, camelCase)
        fields = re.findall(r"['\"`]([a-z_][a-z0-9_]{2,})['\"`]", combined_text)
        collections = re.findall(
            r"db\.([a-z_][a-z0-9_]+)\.", combined_text
        ) + re.findall(
            r"collection[:\s]+['\"]([a-z_][a-z0-9_]+)['\"]", text_lower
        )

        # Risk keywords
        all_keywords = rename_keywords + schema_keywords + query_keywords
        found_keywords = [k for k in all_keywords if k in text_lower]

        return {
            "fields": list(set(fields[:10])),               # max 10 fields
            "collections": list(set(collections[:10])),     # max 10 collections
            "keywords": found_keywords,
            "has_schema_change": any(k in text_lower for k in rename_keywords + schema_keywords),
            "has_query_change": any(k in text_lower for k in query_keywords),
        }

    def _build_description(self, pr_data: dict, files: list, signals: dict) -> str:
        """
        Builds a rich natural language description for Voyage AI embedding.

        The quality of this description directly determines the quality
        of Vector Search matches in Agent 2.

        EXAMPLE OUTPUT:
        "PR 142 titled 'Rename payment_status to payment_state in orders collection'
         modifies 4 files including services/checkout.js and models/order.js.
         This change involves MongoDB field renaming affecting payment_status field
         in the orders and payments collections. Risk signals: rename, field, schema."
        """
        file_names = [f["filename"] for f in files[:5]]
        files_str = ", ".join(file_names) if file_names else "unknown files"

        description = (
            f"PR {pr_data['number']} titled '{pr_data['title']}' "
            f"modifies {len(files)} files including {files_str}. "
        )

        if signals["has_schema_change"]:
            description += (
                f"This change involves MongoDB schema modification "
                f"affecting fields: {', '.join(signals['fields'][:5])} "
                f"in collections: {', '.join(signals['collections'][:5])}. "
            )

        if signals["has_query_change"]:
            description += "This change modifies MongoDB query patterns or aggregation pipelines. "

        if signals["keywords"]:
            description += f"Risk signals detected: {', '.join(signals['keywords'][:8])}."

        return description

    def _write_audit_log(self, action: str, pr_id: int, details: dict):
        """Writes every Harvester action to the audit log collection."""
        self.db[self.settings.COLLECTION_AUDIT_LOG].insert_one({
            "action_type": action,
            "agent_name": "harvester",
            "pr_id": pr_id,
            "details": details,
            "timestamp": datetime.utcnow()
        })
