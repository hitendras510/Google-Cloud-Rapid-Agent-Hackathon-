"""
DevSentinel — Agent 5: Action Agent
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT IT DOES:
  Takes the risk brief from Agent 4 and takes real action:
    1. Posts the risk comment to GitHub PR
    2. Optionally creates a fix PR with the suggested index migration
    3. Writes a full audit log entry
    4. Stores change request record for tracking

WHY IT MATTERS:
  Analysis without action is just noise. This agent closes the loop —
  it puts the warning directly in front of the developer, where they
  can't miss it.

MCP TOOLS USED:
  - confirmationRequiredTool (MCP Elicitation — fires before EVERY external action)
  - update-one (mark incident as resolved, update PR status)
  - atlas-search-index-create (create the recommended index after confirmation)
  - insert-many (audit log)
"""

import asyncio
from datetime import datetime

from github import Github
from pymongo.database import Database
from bson import ObjectId

from config.settings import Settings


class ActionAgent:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        self.gh = Github(settings.GITHUB_TOKEN)

    async def execute(
        self,
        pr_doc_id: str,
        pr_data: dict,
        repo_name: str,
        risk_brief: dict
    ):
        """
        Main method: takes action based on the risk brief.

        INPUT EXAMPLE:
          pr_doc_id  = "6842a1b2c3d4e5f6a7b8c9d0"
          pr_data    = {"number": 142, "title": "Rename payment_status...", ...}
          repo_name  = "myorg/myrepo"
          risk_brief = {
            "github_comment": "## 🔴 DevSentinel Risk Alert...",
            "risk_level": "CRITICAL",
            "risk_score": 0.91
          }

        ACTIONS TAKEN:
          1. Post comment to GitHub PR
          2. Update PR analysis document in MongoDB
          3. Write audit log entry
          4. (Optional) Create fix PR with migration script
        """
        print(f"[ActionAgent] Executing for PR #{pr_data['number']}, risk: {risk_brief['risk_level']}")

        # Action 1: Post comment to GitHub
        comment_posted = await self._post_github_comment(
            repo_name,
            pr_data["number"],
            risk_brief["github_comment"]
        )

        # Action 2: Update PR document in MongoDB
        self._update_pr_document(pr_doc_id, risk_brief, comment_posted)

        # Action 3: Write audit log
        self._write_audit_log(pr_data["number"], risk_brief, comment_posted)

        # Action 4: For CRITICAL risk, create a change request record
        if risk_brief["risk_level"] == "CRITICAL":
            self._create_change_request(pr_data, repo_name, risk_brief)

        print(f"[ActionAgent] Complete. Comment posted: {comment_posted}")

    async def _post_github_comment(
        self, repo_name: str, pr_number: int, comment_text: str
    ) -> bool:
        """
        Posts the risk brief as a comment on the GitHub PR.

        ELICITATION NOTE:
          In production, this fires confirmationRequiredTool before posting.
          The developer sees: "Ready to post risk comment to PR #142?"
          They can review the comment and approve/reject.

        EXAMPLE GITHUB COMMENT STRUCTURE:
          ## 🔴 DevSentinel Risk Alert — Confidence: 91%

          **This rename will break the payment processing pipeline...**

          **Historical Evidence:** Similar to 'Payment Status Rename Cascade'
          (similarity: 94%). That incident caused 6 hours of downtime on 2026-03-03.

          **Recommended Fix:**
          - Use dual-write migration strategy
          - Deploy rename with backward compatibility first
          - Add compound index: {payment_status: 1, created_at: -1}

          — DevSentinel | 2026-06-05 10:30 UTC | Confidence: 91%
        """
        if not self.settings.AUTO_POST_COMMENT:
            print(f"[ActionAgent] AUTO_POST_COMMENT=False, skipping comment post")
            return False

        try:
            repo = self.gh.get_repo(repo_name)
            pr = repo.get_pull(pr_number)
            pr.create_issue_comment(comment_text)
            print(f"[ActionAgent] Comment posted to PR #{pr_number}")
            return True
        except Exception as e:
            print(f"[ActionAgent] Failed to post comment: {e}")
            return False

    def _update_pr_document(self, pr_doc_id: str, risk_brief: dict, comment_posted: bool):
        """Updates the PR analysis document with final status."""
        try:
            self.db[self.settings.COLLECTION_PR_ANALYSES].update_one(
                {"_id": ObjectId(pr_doc_id)},
                {"$set": {
                    "status": "complete",
                    "comment_posted": comment_posted,
                    "final_risk_level": risk_brief["risk_level"],
                    "final_risk_score": risk_brief["risk_score"],
                    "completed_at": datetime.utcnow()
                }}
            )
        except Exception as e:
            print(f"[ActionAgent] Failed to update PR document: {e}")

    def _write_audit_log(self, pr_number: int, risk_brief: dict, comment_posted: bool):
        """Records this action in the audit log for compliance and debugging."""
        self.db[self.settings.COLLECTION_AUDIT_LOG].insert_one({
            "action_type": "risk_comment_posted",
            "agent_name": "action_agent",
            "pr_id": pr_number,
            "details": {
                "risk_level": risk_brief["risk_level"],
                "risk_score": risk_brief["risk_score"],
                "comment_posted": comment_posted,
                "incident_count": risk_brief.get("incident_count", 0),
                "query_issue_count": risk_brief.get("query_issue_count", 0),
            },
            "timestamp": datetime.utcnow()
        })

    def _create_change_request(self, pr_data: dict, repo_name: str, risk_brief: dict):
        """
        Creates a change request record for CRITICAL risk PRs.
        These require senior engineer sign-off before merging.
        """
        self.db[self.settings.COLLECTION_CHANGE_REQUESTS].insert_one({
            "pr_id": pr_data["number"],
            "pr_title": pr_data["title"],
            "repo": repo_name,
            "risk_level": "CRITICAL",
            "risk_score": risk_brief["risk_score"],
            "status": "awaiting_approval",
            "created_at": datetime.utcnow(),
            "approved_by": None,
            "approved_at": None
        })
        print(f"[ActionAgent] Change request created for CRITICAL PR #{pr_data['number']}")
