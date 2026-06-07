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
from contextlib import asynccontextmanager
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()  # Load .env before Settings reads env vars

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from agents.harvester import HarvesterAgent
from agents.analyst import AnalystAgent
from agents.scale_tester import ScaleTesterAgent
from agents.risk_narrator import RiskNarratorAgent
from agents.action_agent import ActionAgent
from config.settings import Settings
from config.database import get_db, ping

# ── Globals (populated at startup) ───────────────────────────────
settings: Settings = None
db = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle — DB connection is made here, not at import time."""
    global settings, db
    settings = Settings()
    try:
        db = get_db()
        ok = ping()
        print(f"[Startup] MongoDB connected: {ok}")
    except Exception as e:
        print(f"[Startup] WARNING: MongoDB not connected — {e}")
        db = None
    yield
    print("[Shutdown] DevSentinel shutting down.")


app = FastAPI(
    title="DevSentinel",
    description="Autonomous Production Safety Agent — MongoDB Atlas + Gemini 2.5 Flash",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health check ─────────────────────────────────────────────────
@app.get("/")
async def root():
    return {
        "service": "DevSentinel",
        "status": "running",
        "version": "1.0.0",
        "db_connected": db is not None,
        "agents": ["Harvester", "Analyst", "ScaleTester", "RiskNarrator", "ActionAgent"],
    }


@app.get("/health")
async def health():
    db_ok = ping() if db is not None else False
    return {
        "status": "healthy" if db_ok else "degraded",
        "db": "connected" if db_ok else "disconnected",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ── GitHub Webhook ────────────────────────────────────────────────
@app.post("/webhook/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receives GitHub PR events.
    Verifies HMAC-SHA256 signature, then runs the 5-agent pipeline in background.
    Supports: opened, synchronize (new commits pushed to PR)
    """
    payload = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    # Skip signature check if no secret is configured (local dev)
    if settings.GITHUB_WEBHOOK_SECRET:
        if not verify_github_signature(payload, signature, settings.GITHUB_WEBHOOK_SECRET):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = request.headers.get("X-GitHub-Event", "")
    action = data.get("action", "")

    # Process PR opened and synchronize (new commits) events
    if event_type != "pull_request" or action not in ("opened", "synchronize"):
        return JSONResponse({"status": "ignored", "reason": f"event={event_type} action={action}"})

    pr_data = data.get("pull_request", {})
    repo_name = data.get("repository", {}).get("full_name", "")

    if not pr_data or not repo_name:
        raise HTTPException(status_code=400, detail="Missing pull_request or repository data")

    background_tasks.add_task(run_full_pipeline, pr_data, repo_name)

    return JSONResponse({
        "status": "pipeline_started",
        "pr_number": pr_data["number"],
        "pr_title": pr_data["title"],
        "action": action,
    })


# ── Query Trigger (Atlas Change Stream calls this) ────────────────
@app.post("/trigger/query")
async def query_trigger(request: Request, background_tasks: BackgroundTasks):
    """Called by Atlas Change Stream watcher when a new query pattern is detected."""
    data = await request.json()
    background_tasks.add_task(run_query_analysis, data)
    return JSONResponse({"status": "query_analysis_started"})


# ── Manual Pipeline Trigger (for testing) ────────────────────────
@app.post("/trigger/pr")
async def manual_pr_trigger(request: Request, background_tasks: BackgroundTasks):
    """
    Manually trigger the pipeline for a given PR — useful for testing without webhooks.
    Body: {"repo": "org/repo", "pr_number": 42}
    """
    data = await request.json()
    repo = data.get("repo", "")
    pr_number = data.get("pr_number")
    if not repo or not pr_number:
        raise HTTPException(status_code=400, detail="repo and pr_number required")

    # Fetch PR data via GitHub API
    from github import Github
    try:
        gh = Github(settings.GITHUB_TOKEN)
        repo_obj = gh.get_repo(repo)
        pr = repo_obj.get_pull(int(pr_number))
        pr_data = {
            "number": pr.number,
            "title": pr.title,
            "body": pr.body or "",
            "html_url": pr.html_url,
            "user": {"login": pr.user.login},
            "head": {"sha": pr.head.sha, "ref": pr.head.ref},
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"GitHub error: {e}")

    background_tasks.add_task(run_full_pipeline, pr_data, repo)
    return JSONResponse({"status": "pipeline_started", "pr_number": pr_number, "repo": repo})


# ── Core Pipeline ─────────────────────────────────────────────────
async def run_full_pipeline(pr_data: dict, repo_name: str):
    """
    Orchestrates all 5 agents in sequence.
    Agent 1 → then Agents 2 & 3 in parallel → Agent 4 → Agent 5
    """
    print(f"[Pipeline] Starting for PR #{pr_data['number']}: {pr_data['title']}")
    try:
        # Agent 1: Harvest & store the PR
        harvester = HarvesterAgent(db, settings)
        pr_doc_id, pr_summary = await harvester.process_pr(pr_data, repo_name)

        # Agents 2 & 3: Run in parallel for speed
        analyst = AnalystAgent(db, settings)
        scale_tester = ScaleTesterAgent(db, settings)
        analysis_result, scale_result = await asyncio.gather(
            analyst.analyse(pr_summary),
            scale_tester.test(pr_summary),
        )

        # Agent 4: Generate risk brief via Gemini
        narrator = RiskNarratorAgent(settings)
        risk_brief = await narrator.generate(pr_summary, analysis_result, scale_result)

        # Agent 5: Post to GitHub & audit log
        action_agent = ActionAgent(db, settings)
        await action_agent.execute(pr_doc_id, pr_data, repo_name, risk_brief)

        print(f"[Pipeline] ✅ Complete for PR #{pr_data['number']}")
    except Exception as e:
        print(f"[Pipeline] ❌ Error for PR #{pr_data['number']}: {e}")
        raise


async def run_query_analysis(query_data: dict):
    """Runs scale testing on a detected query pattern."""
    try:
        scale_tester = ScaleTesterAgent(db, settings)
        await scale_tester.test_standalone(query_data)
    except Exception as e:
        print(f"[QueryAnalysis] Error: {e}")


# ── Signature Verification ────────────────────────────────────────
def verify_github_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub webhook HMAC-SHA256 signature."""
    if not signature or not secret:
        return False
    secret_bytes = secret.encode("utf-8")
    expected = "sha256=" + hmac.new(secret_bytes, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
