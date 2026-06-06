"""
DevSentinel — Main Entry Point
FastAPI app that receives GitHub webhooks and coordinates the agent pipeline.
Run with: uvicorn main:app --host 0.0.0.0 --port 8080
"""

import os
import json
import hashlib
import hmac
import asyncio
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

from agents.harvester import HarvesterAgent
from agents.analyst import AnalystAgent
from agents.scale_tester import ScaleTesterAgent
from agents.risk_narrator import RiskNarratorAgent
from agents.action_agent import ActionAgent
from config.settings import Settings
from config.database import get_db

app = FastAPI(
    title="DevSentinel",
    description="Autonomous Production Safety Agent",
    version="1.0.0"
)

settings = Settings()
db = get_db()

# ── Health check ─────────────────────────────────────────────────
@app.get("/")
async def root():
    return {
        "status": "DevSentinel is running",
        "version": "1.0.0",
        "agents": ["Harvester", "Analyst", "ScaleTester", "RiskNarrator", "ActionAgent"]
    }

@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

# ── GitHub Webhook ────────────────────────────────────────────────
@app.post("/webhook/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receives GitHub PR events.
    Verifies signature, then runs full 5-agent pipeline in background.
    """
    payload = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    # Verify webhook signature
    if not verify_github_signature(payload, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    data = json.loads(payload)
    event_type = request.headers.get("X-GitHub-Event", "")

    # Only process PR open events
    if event_type != "pull_request" or data.get("action") != "opened":
        return JSONResponse({"status": "ignored", "reason": "not a PR open event"})

    pr_data = data["pull_request"]
    repo_name = data["repository"]["full_name"]

    # Run pipeline in background so webhook returns fast
    background_tasks.add_task(run_full_pipeline, pr_data, repo_name)

    return JSONResponse({
        "status": "pipeline_started",
        "pr_number": pr_data["number"],
        "pr_title": pr_data["title"]
    })

# ── Query Trigger (Atlas Change Stream calls this) ────────────────
@app.post("/trigger/query")
async def query_trigger(request: Request, background_tasks: BackgroundTasks):
    """
    Called by Atlas Change Stream watcher when a new query pattern is detected.
    """
    data = await request.json()
    background_tasks.add_task(run_query_analysis, data)
    return JSONResponse({"status": "query_analysis_started"})

# ── Core Pipeline ─────────────────────────────────────────────────
async def run_full_pipeline(pr_data: dict, repo_name: str):
    """
    Orchestrates all 5 agents in sequence.
    Agent 1 → 2 → 3 (parallel with 2) → 4 → 5
    """
    print(f"[Pipeline] Starting for PR #{pr_data['number']}: {pr_data['title']}")

    # Agent 1: Harvest & store the PR
    harvester = HarvesterAgent(db, settings)
    pr_doc_id, pr_summary = await harvester.process_pr(pr_data, repo_name)

    # Agents 2 & 3: Run in parallel for speed
    analyst = AnalystAgent(db, settings)
    scale_tester = ScaleTesterAgent(db, settings)

    analysis_result, scale_result = await asyncio.gather(
        analyst.analyse(pr_summary),
        scale_tester.test(pr_summary)
    )

    # Agent 4: Generate risk brief
    narrator = RiskNarratorAgent(settings)
    risk_brief = await narrator.generate(pr_summary, analysis_result, scale_result)

    # Agent 5: Post to GitHub (with elicitation)
    action_agent = ActionAgent(db, settings)
    await action_agent.execute(pr_doc_id, pr_data, repo_name, risk_brief)

    print(f"[Pipeline] Complete for PR #{pr_data['number']}")

async def run_query_analysis(query_data: dict):
    """Runs scale testing on a detected query pattern."""
    scale_tester = ScaleTesterAgent(db, settings)
    await scale_tester.test_standalone(query_data)

# ── Signature Verification ────────────────────────────────────────
def verify_github_signature(payload: bytes, signature: str) -> bool:
    if not signature:
        return False
    secret = settings.GITHUB_WEBHOOK_SECRET.encode()
    expected = "sha256=" + hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
