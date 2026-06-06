"""
DevSentinel — Agent 4: Risk Narrator
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT IT DOES:
  Takes all the raw data from Agents 2 and 3 and uses Gemini 2.5 Flash
  to write a clear, actionable, evidence-backed risk brief.
  The output is the exact text that gets posted to GitHub as a PR comment.

WHY IT MATTERS:
  Data without narrative is ignored. Developers need to instantly understand
  WHAT will break, WHY, and WHAT TO DO. Gemini turns JSON into a brief that
  a developer reads in 30 seconds and acts on.

NO MCP TOOLS — pure Gemini reasoning step.
"""

from datetime import datetime
import google.generativeai as genai

from config.settings import Settings


class RiskNarratorAgent:
    def __init__(self, settings: Settings):
        self.settings = settings
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self.model = genai.GenerativeModel(settings.GEMINI_MODEL)

    async def generate(self, pr_summary: dict, analysis_result: dict, scale_result: dict) -> dict:
        """
        Generates the full risk brief for the PR comment.

        INPUT EXAMPLE:
          pr_summary     = {"pr_id": 142, "pr_title": "Rename payment_status...", ...}
          analysis_result = {"risk_score": 0.91, "risk_level": "CRITICAL",
                             "matched_incidents": [{"title": "Payment Rename Cascade",
                             "score": 0.94, "recovery_time_hours": 6}], ...}
          scale_result   = {"overall_query_risk": "CRITICAL",
                            "scale_results": [{"projected_ms": 11400, ...}]}

        OUTPUT EXAMPLE:
          {
            "github_comment": "## 🔴 DevSentinel Risk Alert — Confidence: 91%\n\n...",
            "risk_level": "CRITICAL",
            "risk_score": 0.91,
            "summary_one_line": "This rename will break 3 downstream services",
            "recommended_action": "dual-write migration"
          }
        """
        print(f"[RiskNarrator] Generating brief for PR #{pr_summary.get('pr_id')}")

        risk_score = analysis_result.get("risk_score", 0.5)
        risk_level = analysis_result.get("risk_level", "LOW")
        matched_incidents = analysis_result.get("matched_incidents", [])
        index_warnings = analysis_result.get("index_warnings", [])
        scale_results = scale_result.get("scale_results", [])

        # Build structured prompt for Gemini
        prompt = self._build_prompt(
            pr_summary, risk_score, risk_level,
            matched_incidents, index_warnings, scale_results
        )

        # Call Gemini 2.5 Flash
        try:
            response = self.model.generate_content(prompt)
            github_comment = response.text
        except Exception as e:
            print(f"[RiskNarrator] Gemini error: {e}")
            # Fallback: generate comment from template
            github_comment = self._fallback_comment(
                pr_summary, risk_score, risk_level, matched_incidents, scale_results
            )

        return {
            "github_comment": github_comment,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "has_incidents": len(matched_incidents) > 0,
            "has_query_issues": len(scale_results) > 0,
            "incident_count": len(matched_incidents),
            "query_issue_count": len(scale_results),
        }

    def _build_prompt(
        self, pr_summary, risk_score, risk_level,
        incidents, index_warnings, scale_results
    ) -> str:
        """
        Builds the Gemini prompt. The more structured the input,
        the more accurate and actionable the output.
        """
        # Format incident evidence
        incident_text = ""
        if incidents:
            inc = incidents[0]  # Use top match
            incident_text = (
                f"MOST SIMILAR PAST INCIDENT (similarity: {inc.get('score', 0):.0%}):\n"
                f"  Title: {inc.get('title', 'Unknown')}\n"
                f"  Date: {inc.get('date', 'Unknown')}\n"
                f"  What broke: {inc.get('description', '')[:200]}\n"
                f"  Collections affected: {', '.join(inc.get('collections_affected', []))}\n"
                f"  Recovery time: {inc.get('recovery_time_hours', '?')} hours\n"
                f"  Fix that worked: {inc.get('fix_applied', 'Unknown')}\n"
            )
        else:
            incident_text = "NO SIMILAR PAST INCIDENTS FOUND (this may be a new pattern)"

        # Format query warnings
        query_text = ""
        if scale_results:
            qr = scale_results[0]
            query_text = (
                f"QUERY SCALE WARNING:\n"
                f"  Collection: {qr.get('collection', '?')}\n"
                f"  Query: {qr.get('query_text', '?')[:150]}\n"
                f"  Collection scan: {qr.get('is_collection_scan', False)}\n"
                f"  Current speed: {qr.get('current_ms', '?')}ms\n"
                f"  At 10x data: {qr.get('projected_ms', '?')}ms\n"
                f"  Missing index: {qr.get('missing_index', 'None')}\n"
            )
        else:
            query_text = "NO QUERY PERFORMANCE ISSUES DETECTED"

        # Index warnings
        index_text = "\n".join(index_warnings) if index_warnings else "No active index conflicts"

        prompt = f"""You are DevSentinel, an autonomous production safety agent for engineering teams.
A developer has opened a GitHub pull request and you must write a risk warning comment.

PR DETAILS:
  Number: #{pr_summary.get('pr_id', '?')}
  Title: {pr_summary.get('pr_title', '?')}
  Author: {pr_summary.get('pr_author', '?')}
  Files changed: {len(pr_summary.get('files_changed', []))}

RISK ASSESSMENT:
  Risk Score: {risk_score:.0%}
  Risk Level: {risk_level}

{incident_text}

{query_text}

INDEX WARNINGS:
{index_text}

INSTRUCTIONS:
Write a GitHub PR comment in Markdown format. Include:

1. A header with risk badge:
   - 🔴 CRITICAL if risk >= 80%
   - 🟡 HIGH if risk >= 50%
   - 🟢 LOW if risk < 50%
   Format: "## [badge] DevSentinel Risk Alert — Confidence: [score]%"

2. ONE bold sentence explaining exactly what will break and why.

3. "**Historical Evidence:**" section — if incidents exist, cite the specific past incident
   with its date, what broke, and recovery time. Be specific, not generic.

4. "**Query Performance Warning:**" section — if query issues exist, show current vs projected time.
   If no query issues, omit this section entirely.

5. "**Recommended Fix:**" section — 3 bullet points, specific and actionable.
   Reference the fix that worked last time if available.

6. A footer: "— DevSentinel | [timestamp] | Confidence: [score]%"

Keep total length under 350 words. Be specific, technical, and direct. No filler phrases.
"""
        return prompt

    def _fallback_comment(
        self, pr_summary, risk_score, risk_level, matched_incidents, scale_results
    ) -> str:
        """Template-based comment when Gemini is unavailable."""
        badge = "🔴" if risk_level == "CRITICAL" else "🟡" if risk_level == "HIGH" else "🟢"
        comment = f"## {badge} DevSentinel Risk Alert — Confidence: {risk_score:.0%}\n\n"
        comment += f"**Risk Level: {risk_level}** — Automated analysis of PR #{pr_summary.get('pr_id')}\n\n"

        if matched_incidents:
            inc = matched_incidents[0]
            comment += f"**Historical Evidence:** Similar to '{inc.get('title', 'Unknown')}' "
            comment += f"(similarity: {inc.get('score', 0):.0%}). "
            comment += f"Recovery time: {inc.get('recovery_time_hours', '?')} hours.\n\n"

        if scale_results:
            qr = scale_results[0]
            comment += f"**Query Performance Warning:** Collection scan detected on `{qr.get('collection')}`. "
            comment += f"Current: {qr.get('current_ms')}ms → 10x data: {qr.get('projected_ms')}ms\n\n"

        comment += "**Recommended Fix:**\n"
        comment += "- Review schema changes for downstream impact\n"
        comment += "- Add indexes before deploying to production\n"
        comment += "- Test with production-scale data volume\n\n"
        comment += f"— DevSentinel | {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} | Confidence: {risk_score:.0%}"
        return comment
