"""
DevSentinel — Premium Streamlit Dashboard
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Full monitoring UI with live KPIs, animated risk feed, charts, and agent trace.
Run with: streamlit run dashboard/app.py
"""

import os
import sys
import time
from datetime import datetime, timedelta
from collections import Counter

import pymongo
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from dotenv import load_dotenv

# ── Path fix so imports work from dashboard/ subdirectory ─────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PAGE CONFIG — must be first Streamlit call
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.set_page_config(
    page_title="DevSentinel",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GLOBAL CSS — glassmorphism dark theme
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.markdown("""
<style>
/* ── Google Font ─────────────────────────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── Root palette ────────────────────────────────────────────── */
:root {
    --bg-deep:    #080c14;
    --bg-card:    rgba(255,255,255,0.04);
    --bg-card-hv: rgba(255,255,255,0.08);
    --border:     rgba(255,255,255,0.08);
    --accent:     #00d9ff;
    --accent2:    #7c3aed;
    --red:        #ff4757;
    --amber:      #ffa502;
    --green:      #2ed573;
    --text-1:     #f1f5f9;
    --text-2:     #94a3b8;
    --text-3:     #64748b;
}

/* ── Base ────────────────────────────────────────────────────── */
html, body, [data-testid="stAppViewContainer"] {
    background: var(--bg-deep) !important;
    font-family: 'Inter', sans-serif !important;
    color: var(--text-1) !important;
}
[data-testid="stSidebar"] {
    background: rgba(8,12,20,0.95) !important;
    border-right: 1px solid var(--border) !important;
    backdrop-filter: blur(20px);
}
[data-testid="stHeader"] { background: transparent !important; }

/* ── Hide Streamlit chrome ───────────────────────────────────── */
#MainMenu, footer, [data-testid="stToolbar"] { visibility: hidden; }
.block-container { padding: 1.5rem 2rem 3rem !important; max-width: 100% !important; }

/* ── Metric card override ────────────────────────────────────── */
[data-testid="metric-container"] {
    background: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-radius: 16px !important;
    padding: 1.2rem 1.5rem !important;
    backdrop-filter: blur(12px);
    transition: border-color 0.3s, transform 0.2s;
}
[data-testid="metric-container"]:hover {
    border-color: var(--accent) !important;
    transform: translateY(-2px);
}
[data-testid="stMetricLabel"] > div {
    color: var(--text-2) !important;
    font-size: 0.75rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.08em !important;
    text-transform: uppercase !important;
}
[data-testid="stMetricValue"] > div {
    color: var(--text-1) !important;
    font-size: 2rem !important;
    font-weight: 700 !important;
}
[data-testid="stMetricDelta"] > div { font-size: 0.8rem !important; }

/* ── Glass card ─────────────────────────────────────────────── */
.glass-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 1.5rem;
    backdrop-filter: blur(12px);
    margin-bottom: 1rem;
    transition: border-color 0.3s, box-shadow 0.3s;
}
.glass-card:hover {
    border-color: rgba(0,217,255,0.25);
    box-shadow: 0 0 30px rgba(0,217,255,0.07);
}

/* ── Section headers ─────────────────────────────────────────── */
.section-title {
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: var(--text-3);
    margin-bottom: 1rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid var(--border);
}

/* ── Risk badge ──────────────────────────────────────────────── */
.badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
}
.badge-critical { background: rgba(255,71,87,0.15); color: #ff4757; border: 1px solid rgba(255,71,87,0.4); }
.badge-high     { background: rgba(255,165,2,0.15);  color: #ffa502; border: 1px solid rgba(255,165,2,0.4); }
.badge-low      { background: rgba(46,213,115,0.15); color: #2ed573; border: 1px solid rgba(46,213,115,0.4); }
.badge-none     { background: rgba(100,116,139,0.15);color: #94a3b8; border: 1px solid rgba(100,116,139,0.3); }

/* ── Log row ─────────────────────────────────────────────────── */
.log-row {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.6rem 0.8rem;
    border-radius: 10px;
    margin-bottom: 0.4rem;
    background: rgba(255,255,255,0.02);
    border: 1px solid rgba(255,255,255,0.04);
    transition: background 0.2s;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.78rem;
}
.log-row:hover { background: rgba(255,255,255,0.05); }
.log-time  { color: var(--accent); min-width: 60px; }
.log-agent { color: var(--accent2); }
.log-action{ color: var(--text-1); font-weight: 500; }
.log-pr    { color: var(--text-2); }

/* ── PR row ──────────────────────────────────────────────────── */
.pr-row {
    padding: 0.9rem 1rem;
    border-radius: 12px;
    margin-bottom: 0.5rem;
    background: rgba(255,255,255,0.02);
    border: 1px solid rgba(255,255,255,0.05);
    transition: all 0.2s;
}
.pr-row:hover {
    background: rgba(0,217,255,0.04);
    border-color: rgba(0,217,255,0.15);
}
.pr-title { font-size: 0.9rem; font-weight: 500; color: var(--text-1); }
.pr-meta  { font-size: 0.75rem; color: var(--text-3); margin-top: 2px; font-family: 'JetBrains Mono', monospace; }

/* ── Pulse dot ───────────────────────────────────────────────── */
.pulse-dot {
    display: inline-block;
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--green);
    box-shadow: 0 0 0 0 rgba(46,213,115,0.4);
    animation: pulse-anim 2s infinite;
    margin-right: 6px;
    vertical-align: middle;
}
@keyframes pulse-anim {
    0%   { box-shadow: 0 0 0 0 rgba(46,213,115,0.4); }
    70%  { box-shadow: 0 0 0 8px rgba(46,213,115,0); }
    100% { box-shadow: 0 0 0 0 rgba(46,213,115,0); }
}

/* ── Scrollbar ───────────────────────────────────────────────── */
::-webkit-scrollbar       { width: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 10px; }

/* ── Sidebar nav button ──────────────────────────────────────── */
[data-testid="stSidebarNav"] a {
    color: var(--text-2) !important;
    font-size: 0.85rem !important;
    border-radius: 8px !important;
    transition: all 0.2s !important;
}
[data-testid="stSidebarNav"] a:hover { color: var(--accent) !important; }

/* ── Plotly chart bg ─────────────────────────────────────────── */
.js-plotly-plot .plotly { background: transparent !important; }

/* ── Tab styling ─────────────────────────────────────────────── */
[data-baseweb="tab-list"] {
    background: rgba(255,255,255,0.03) !important;
    border-radius: 12px !important;
    padding: 4px !important;
    border: 1px solid var(--border) !important;
    gap: 4px !important;
}
[data-baseweb="tab"] {
    border-radius: 8px !important;
    color: var(--text-2) !important;
    font-weight: 500 !important;
}
[aria-selected="true"][data-baseweb="tab"] {
    background: rgba(0,217,255,0.1) !important;
    color: var(--accent) !important;
}

/* ── Selectbox ────────────────────────────────────────────────── */
[data-baseweb="select"] > div {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    color: var(--text-1) !important;
}

/* ── Progress bar ────────────────────────────────────────────── */
[data-testid="stProgress"] > div > div {
    background: linear-gradient(90deg, var(--accent2), var(--accent)) !important;
    border-radius: 4px !important;
}

/* ── Info / warning / error boxes ────────────────────────────── */
.stAlert { border-radius: 10px !important; }

/* ── Divider ─────────────────────────────────────────────────── */
hr { border-color: var(--border) !important; margin: 1.5rem 0 !important; }
</style>
""", unsafe_allow_html=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DATABASE CONNECTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@st.cache_resource(show_spinner=False)
def get_db():
    uri = os.environ.get("MONGODB_URI", "")
    if not uri:
        return None
    try:
        client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=3000)
        client.admin.command("ping")
        return client[os.environ.get("MONGODB_DB_NAME", "devsentiinel")]
    except Exception:
        return None


db = get_db()
db_ok = db is not None

# BUG FIX: Define today_start at module level so ALL pages can access it
now = datetime.utcnow()
today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

# ── MOCK DATA FOR DEMO MODE ────────────────────────────────────
MOCK_PAST_INCIDENTS = [
    {
        "title": "Payment Status Field Rename Cascade Failure",
        "description": (
            "Engineer renamed payment_status to payment_state in the orders collection "
            "without updating downstream services. The checkout service, analytics pipeline, "
            "and refund processor all read payment_status and began returning null values. "
            "This caused 100% of payment status checks to fail silently."
        ),
        "field_changed": "payment_status",
        "collections_affected": ["orders", "refunds", "analytics"],
        "services_affected": ["checkout-service", "analytics-pipeline", "refund-processor"],
        "fix_applied": "Dual-write migration: wrote to both payment_status and payment_state for 48h, then deprecated old field",
        "recovery_time_hours": 6,
        "severity": "P0",
        "date": (now - timedelta(days=90)).strftime("%Y-%m-%d"),
        "root_cause": "No backward compatibility window, immediate hard cutover",
        "lesson_learned": "Always use dual-write for field renames. Never hard-cut."
    },
    {
        "title": "Missing Compound Index Caused Orders Page Timeout",
        "description": (
            "New feature added db.orders.find({customerId, status}).sort({createdAt:-1}) "
            "query without a compound index. On dev (1,200 docs) response was 20ms. "
            "In production (800,000 docs) query took 14 seconds and caused request timeouts."
        ),
        "field_changed": "customerId",
        "collections_affected": ["orders"],
        "services_affected": ["order-service", "customer-portal"],
        "fix_applied": "db.orders.createIndex({customerId:1, status:1, createdAt:-1}) — immediate relief",
        "recovery_time_hours": 2,
        "severity": "P1",
        "date": (now - timedelta(days=45)).strftime("%Y-%m-%d"),
        "root_cause": "Collection scan on high-cardinality field without index",
        "lesson_learned": "All queries on orders collection require compound index review before deploy"
    },
    {
        "title": "Schema Migration Without Backfill Broke Analytics",
        "description": (
            "Added new required field 'region' to the users collection. "
            "Existing 2.3M user documents did not have this field. "
            "Analytics dashboards showing user segmentation by region returned empty data "
            "for all records created before the migration."
        ),
        "field_changed": "region",
        "collections_affected": ["users", "analytics"],
        "services_affected": ["analytics-service", "reporting-dashboard"],
        "fix_applied": "Backfill script to add region='unknown' to all existing documents, then re-run analytics",
        "recovery_time_hours": 4,
        "severity": "P1",
        "date": (now - timedelta(days=120)).strftime("%Y-%m-%d"),
        "root_cause": "New field added without default value or backfill for existing documents",
        "lesson_learned": "Schema changes must include migration script for existing data"
    },
    {
        "title": "Index Drop Caused Full Collection Scan in Prod",
        "description": (
            "PR to 'clean up indexes' removed the email_1 index from users collection, "
            "believing it was unused. Login queries (find by email) went from 2ms to 8 seconds. "
            "User login failure rate hit 34%."
        ),
        "field_changed": "email",
        "collections_affected": ["users"],
        "services_affected": ["auth-service", "user-service"],
        "fix_applied": "Recreated db.users.createIndex({email:1}, {unique:true}) — query time back to 2ms",
        "recovery_time_hours": 1,
        "severity": "P0",
        "date": (now - timedelta(days=60)).strftime("%Y-%m-%d"),
        "root_cause": "Index usage was not checked before removal (Atlas Performance Advisor not consulted)",
        "lesson_learned": "Always check Atlas Performance Advisor before dropping any index"
    },
    {
        "title": "Aggregation Pipeline $lookup Without Index Timed Out",
        "description": (
            "New reporting feature added $lookup from orders to products without an index "
            "on the foreign key. Pipeline took 45 seconds on 500K orders, "
            "causing gateway timeout on the reporting endpoint."
        ),
        "field_changed": "productId",
        "collections_affected": ["orders", "products"],
        "services_affected": ["reporting-service"],
        "fix_applied": "Added {productId:1} index to products collection. Pipeline time: 45s → 0.3s",
        "recovery_time_hours": 1,
        "severity": "P2",
        "date": (now - timedelta(days=30)).strftime("%Y-%m-%d"),
        "root_cause": "$lookup foreign field not indexed",
        "lesson_learned": "All $lookup foreign fields must have indexes"
    },
    {
        "title": "Unindexed Sort Caused Memory Limit Exceeded Error",
        "description": (
            "Reporting query sorted 2M documents without an index on the sort field. "
            "MongoDB threw 'Executor error: OperationFailed: Sort exceeded memory limit of 100MB'."
        ),
        "field_changed": "createdAt",
        "collections_affected": ["transactions"],
        "services_affected": ["finance-reporting"],
        "fix_applied": "Added {createdAt:-1} index. Added allowDiskUse:true as temporary workaround",
        "recovery_time_hours": 3,
        "severity": "P1",
        "date": (now - timedelta(days=75)).strftime("%Y-%m-%d"),
        "root_cause": "In-memory sort limit hit on unindexed field with large result set",
        "lesson_learned": "Always index sort fields. Use allowDiskUse as emergency fallback only."
    }
]

MOCK_PR_ANALYSES = [
    {
        "pr_id": 142,
        "pr_title": "Rename payment_status to payment_state in orders schema",
        "pr_url": "https://github.com/AbhishekGupta0164/Google-Cloud-Rapid-Agent-Hackathon-/pull/142",
        "pr_author": "johndoe",
        "repo": "checkout-service",
        "description": "Rename the order status field to match our new naming standard. Also update downstream checkout APIs.",
        "files_changed": ["models/Order.js", "controllers/Checkout.js", "tests/checkout.test.js"],
        "mongo_fields_changed": ["payment_status", "payment_state"],
        "collections_mentioned": ["orders", "refunds", "analytics"],
        "risk_keywords": ["rename", "status"],
        "has_schema_change": True,
        "has_query_change": True,
        "timestamp": now - timedelta(minutes=45),
        "status": "complete",
        "risk_score": 0.92,
        "risk_level": "CRITICAL",
        "matched_incidents": [MOCK_PAST_INCIDENTS[0]],
        "index_warnings": ["No compound index found matching sorting fields: {customerId: 1, status: 1}"],
        "comment_posted": True
    },
    {
        "pr_id": 141,
        "pr_title": "Refactor transactions aggregation pipeline",
        "pr_url": "https://github.com/AbhishekGupta0164/Google-Cloud-Rapid-Agent-Hackathon-/pull/141",
        "pr_author": "alice",
        "repo": "finance-backend",
        "description": "Implements new lookup logic for transactions aggregation pipeline to join customer profiles.",
        "files_changed": ["pipelines/transactions.py", "db/queries.py"],
        "mongo_fields_changed": ["customerId"],
        "collections_mentioned": ["transactions", "users"],
        "risk_keywords": ["aggregate", "lookup"],
        "has_schema_change": False,
        "has_query_change": True,
        "timestamp": now - timedelta(hours=3),
        "status": "complete",
        "risk_score": 0.68,
        "risk_level": "HIGH",
        "matched_incidents": [MOCK_PAST_INCIDENTS[4]],
        "index_warnings": [],
        "comment_posted": True
    },
    {
        "pr_id": 140,
        "pr_title": "Add user region field to database model",
        "pr_url": "https://github.com/AbhishekGupta0164/Google-Cloud-Rapid-Agent-Hackathon-/pull/140",
        "pr_author": "bob_developer",
        "repo": "user-service",
        "description": "Add region support to user schemas to support localized regulatory compliance checks.",
        "files_changed": ["schemas/User.js", "services/UserManagement.js"],
        "mongo_fields_changed": ["region"],
        "collections_mentioned": ["users", "analytics"],
        "risk_keywords": ["add field", "schema"],
        "has_schema_change": True,
        "has_query_change": False,
        "timestamp": now - timedelta(hours=6),
        "status": "complete",
        "risk_score": 0.74,
        "risk_level": "HIGH",
        "matched_incidents": [MOCK_PAST_INCIDENTS[2]],
        "index_warnings": ["No default value or backfill migration found for new required field 'region'!"],
        "comment_posted": True
    },
    {
        "pr_id": 139,
        "pr_title": "Clean up unused database indexes",
        "pr_url": "https://github.com/AbhishekGupta0164/Google-Cloud-Rapid-Agent-Hackathon-/pull/139",
        "pr_author": "admin_dave",
        "repo": "infrastructure",
        "description": "Removes outdated indexes on users collection to improve write performance.",
        "files_changed": ["scripts/cleanup_indexes.js"],
        "mongo_fields_changed": [],
        "collections_mentioned": ["users"],
        "risk_keywords": ["drop index"],
        "has_schema_change": True,
        "has_query_change": False,
        "timestamp": now - timedelta(hours=14),
        "status": "complete",
        "risk_score": 0.88,
        "risk_level": "CRITICAL",
        "matched_incidents": [MOCK_PAST_INCIDENTS[3]],
        "index_warnings": ["Warning: Dropping 'email_1' might impact high-frequency queries in auth-service."],
        "comment_posted": True
    },
    {
        "pr_id": 138,
        "pr_title": "Update README deployment instructions",
        "pr_url": "https://github.com/AbhishekGupta0164/Google-Cloud-Rapid-Agent-Hackathon-/pull/138",
        "pr_author": "charlie_ux",
        "repo": "auth-portal",
        "description": "Minor changes to documentation to clarify local running process.",
        "files_changed": ["README.md"],
        "mongo_fields_changed": [],
        "collections_mentioned": [],
        "risk_keywords": [],
        "has_schema_change": False,
        "has_query_change": False,
        "timestamp": now - timedelta(days=1, hours=2),
        "status": "complete",
        "risk_score": 0.04,
        "risk_level": "LOW",
        "matched_incidents": [],
        "index_warnings": [],
        "comment_posted": False
    },
    {
        "pr_id": 137,
        "pr_title": "Optimize login find query performance",
        "pr_url": "https://github.com/AbhishekGupta0164/Google-Cloud-Rapid-Agent-Hackathon-/pull/137",
        "pr_author": "alice",
        "repo": "auth-service",
        "description": "Improve user lookup by ensuring lowercase normalization of emails.",
        "files_changed": ["controllers/Auth.js"],
        "mongo_fields_changed": ["email"],
        "collections_mentioned": ["users"],
        "risk_keywords": ["find", "email"],
        "has_schema_change": False,
        "has_query_change": True,
        "timestamp": now - timedelta(days=2),
        "status": "complete",
        "risk_score": 0.12,
        "risk_level": "LOW",
        "matched_incidents": [],
        "index_warnings": [],
        "comment_posted": False
    }
]

MOCK_AUDIT_LOG = [
    {
        "action_type": "risk_comment_posted",
        "agent_name": "action_agent",
        "pr_id": 142,
        "details": {"risk_level": "CRITICAL", "risk_score": 0.92, "comment_posted": True},
        "timestamp": now - timedelta(minutes=40)
    },
    {
        "action_type": "report_generated",
        "agent_name": "risk_narrator",
        "pr_id": 142,
        "details": {"risk_level": "CRITICAL", "risk_score": 0.92},
        "timestamp": now - timedelta(minutes=42)
    },
    {
        "action_type": "scale_test_failed",
        "agent_name": "scale_tester",
        "pr_id": 142,
        "details": {"is_collection_scan": True, "suggested_index": "{customerId: 1, status: 1}"},
        "timestamp": now - timedelta(minutes=43)
    },
    {
        "action_type": "similarity_search",
        "agent_name": "analyst",
        "pr_id": 142,
        "details": {"matched_incidents_count": 1, "top_match_score": 0.89},
        "timestamp": now - timedelta(minutes=44)
    },
    {
        "action_type": "pr_received",
        "agent_name": "harvester",
        "pr_id": 142,
        "details": {"repo": "checkout-service", "files_changed": 3},
        "timestamp": now - timedelta(minutes=45)
    },
    {
        "action_type": "risk_comment_posted",
        "agent_name": "action_agent",
        "pr_id": 141,
        "details": {"risk_level": "HIGH", "risk_score": 0.68, "comment_posted": True},
        "timestamp": now - timedelta(hours=2, minutes=55)
    },
    {
        "action_type": "report_generated",
        "agent_name": "risk_narrator",
        "pr_id": 141,
        "details": {"risk_level": "HIGH", "risk_score": 0.68},
        "timestamp": now - timedelta(hours=2, minutes=57)
    },
    {
        "action_type": "similarity_search",
        "agent_name": "analyst",
        "pr_id": 141,
        "details": {"matched_incidents_count": 1, "top_match_score": 0.72},
        "timestamp": now - timedelta(hours=2, minutes=59)
    },
    {
        "action_type": "pr_received",
        "agent_name": "harvester",
        "pr_id": 141,
        "details": {"repo": "finance-backend", "files_changed": 2},
        "timestamp": now - timedelta(hours=3)
    },
    {
        "action_type": "risk_comment_posted",
        "agent_name": "action_agent",
        "pr_id": 140,
        "details": {"risk_level": "HIGH", "risk_score": 0.74, "comment_posted": True},
        "timestamp": now - timedelta(hours=5, minutes=55)
    },
    {
        "action_type": "report_generated",
        "agent_name": "risk_narrator",
        "pr_id": 140,
        "details": {"risk_level": "HIGH", "risk_score": 0.74},
        "timestamp": now - timedelta(hours=5, minutes=58)
    },
    {
        "action_type": "pr_received",
        "agent_name": "harvester",
        "pr_id": 140,
        "details": {"repo": "user-service", "files_changed": 2},
        "timestamp": now - timedelta(hours=6)
    },
    {
        "action_type": "risk_comment_posted",
        "agent_name": "action_agent",
        "pr_id": 139,
        "details": {"risk_level": "CRITICAL", "risk_score": 0.88, "comment_posted": True},
        "timestamp": now - timedelta(hours=13, minutes=50)
    },
    {
        "action_type": "report_generated",
        "agent_name": "risk_narrator",
        "pr_id": 139,
        "details": {"risk_level": "CRITICAL", "risk_score": 0.88},
        "timestamp": now - timedelta(hours=13, minutes=52)
    },
    {
        "action_type": "similarity_search",
        "agent_name": "analyst",
        "pr_id": 139,
        "details": {"matched_incidents_count": 1, "top_match_score": 0.85},
        "timestamp": now - timedelta(hours=13, minutes=55)
    },
    {
        "action_type": "pr_received",
        "agent_name": "harvester",
        "pr_id": 139,
        "details": {"repo": "infrastructure", "files_changed": 1},
        "timestamp": now - timedelta(hours=14)
    }
]

MOCK_QUERY_PATTERNS = [
    {
        "collection": "orders",
        "operation": "find",
        "query_text": "db.orders.find({customerId: '12345', status: 'ACTIVE'}).sort({createdAt: -1})",
        "description": "Risky query without compound index. Causes collection scan on orders.",
        "is_collection_scan": True,
        "risk_level": "CRITICAL",
        "suggested_index": "db.orders.createIndex({customerId: 1, status: 1, createdAt: -1})",
        "timestamp": now - timedelta(minutes=43)
    },
    {
        "collection": "transactions",
        "operation": "find",
        "query_text": "db.transactions.find({}).sort({createdAt: -1})",
        "description": "Sorting large result set without index. Leads to in-memory sort warning.",
        "is_collection_scan": False,
        "risk_level": "HIGH",
        "suggested_index": "db.transactions.createIndex({createdAt: -1})",
        "timestamp": now - timedelta(hours=3, minutes=5)
    },
    {
        "collection": "users",
        "operation": "find",
        "query_text": "db.users.find({email: 'test@example.com'})",
        "description": "Login query running without index after index drop.",
        "is_collection_scan": True,
        "risk_level": "CRITICAL",
        "suggested_index": "db.users.createIndex({email: 1}, {unique: true})",
        "timestamp": now - timedelta(hours=13, minutes=56)
    }
]

MOCK_CHANGE_REQUESTS = [
    {
        "pr_id": 142,
        "pr_title": "Rename payment_status to payment_state in orders schema",
        "repo": "checkout-service",
        "risk_level": "CRITICAL",
        "risk_score": 0.92,
        "status": "awaiting_approval",
        "created_at": now - timedelta(minutes=45),
        "approved_by": None,
        "approved_at": None
    },
    {
        "pr_id": 139,
        "pr_title": "Clean up unused database indexes",
        "repo": "infrastructure",
        "risk_level": "CRITICAL",
        "risk_score": 0.88,
        "status": "approved",
        "created_at": now - timedelta(hours=14),
        "approved_by": "lead_dave",
        "approved_at": now - timedelta(hours=13)
    }
]


def get_mock_collection(name: str) -> list:
    if name == "past_incidents":
        return MOCK_PAST_INCIDENTS
    elif name == "pr_analyses":
        return MOCK_PR_ANALYSES
    elif name in ("audit_log", "audit_logs"):
        return MOCK_AUDIT_LOG
    elif name == "query_patterns":
        return MOCK_QUERY_PATTERNS
    elif name == "change_requests":
        return MOCK_CHANGE_REQUESTS
    return []


def safe_count(collection_name: str, query: dict = None) -> int:
    if not db_ok:
        items = get_mock_collection(collection_name)
        if not query:
            return len(items)
        count = 0
        for item in items:
            match = True
            for k, v in query.items():
                if k == "timestamp":
                    if "$gte" in v:
                        item_ts = item.get("timestamp") or item.get("created_at") or now
                        if not isinstance(item_ts, datetime):
                            continue
                        if item_ts < v["$gte"]:
                            match = False
                            break
                elif k == "action_type":
                    if item.get("action_type") != v:
                        match = False
                        break
                elif k == "risk_level":
                    if item.get("risk_level") != v:
                        match = False
                        break
                elif k == "status":
                    if item.get("status") != v:
                        match = False
                        break
            if match:
                count += 1
        return count

    try:
        return db[collection_name].count_documents(query or {})
    except Exception:
        return 0


def safe_find(collection_name: str, query: dict = None, sort_field: str = "timestamp",
              limit: int = 10, exclude: list = None) -> list:
    if not db_ok:
        items = get_mock_collection(collection_name)
        filtered_items = []
        for item in items:
            match = True
            if query:
                for k, v in query.items():
                    if k == "timestamp":
                        if "$gte" in v:
                            item_ts = item.get("timestamp") or item.get("created_at") or now
                            if not isinstance(item_ts, datetime):
                                continue
                            if item_ts < v["$gte"]:
                                match = False
                                break
                    elif k == "action_type":
                        if item.get("action_type") != v:
                            match = False
                            break
                    elif k == "risk_level":
                        if item.get("risk_level") != v:
                            match = False
                            break
                    elif k == "status":
                        if item.get("status") != v:
                            match = False
                            break
            if match:
                filtered_items.append(dict(item))
        if sort_field:
            def sort_key(x):
                val = x.get(sort_field)
                if val is None:
                    val = x.get("timestamp") or x.get("created_at") or x.get("date") or ""
                return val
            filtered_items.sort(key=sort_key, reverse=True)
        return filtered_items[:limit]

    try:
        projection = {k: 0 for k in (exclude or [])}
        cursor = db[collection_name].find(query or {}, projection if projection else None)
        if sort_field:
            cursor = cursor.sort(sort_field, -1)
        return list(cursor.limit(limit))
    except Exception:
        return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SIDEBAR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with st.sidebar:
    st.markdown("""
    <div style="padding:1.2rem 0 1.5rem;">
        <div style="font-size:1.5rem;font-weight:800;color:#f1f5f9;letter-spacing:-0.5px;">
            🛡️ DevSentinel
        </div>
        <div style="font-size:0.72rem;color:#64748b;margin-top:4px;letter-spacing:0.05em;">
            AUTONOMOUS PRODUCTION SAFETY
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Connection status
    if db_ok:
        st.markdown('<div style="display:flex;align-items:center;gap:8px;padding:8px 12px;'
                    'background:rgba(46,213,115,0.08);border:1px solid rgba(46,213,115,0.2);'
                    'border-radius:10px;margin-bottom:1rem;">'
                    '<span class="pulse-dot"></span>'
                    '<span style="font-size:0.78rem;color:#2ed573;font-weight:500;">MongoDB Connected</span>'
                    '</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div style="display:flex;align-items:center;gap:8px;padding:8px 12px;'
                    'background:rgba(0,217,255,0.08);border:1px solid rgba(0,217,255,0.2);'
                    'border-radius:10px;margin-bottom:1rem;">'
                    '<span class="pulse-dot" style="background:#00d9ff;box-shadow:0 0 0 0 rgba(0,217,255,0.4);"></span>'
                    '<span style="font-size:0.78rem;color:#00d9ff;font-weight:500;">Demo Mode Active</span>'
                    '</div>', unsafe_allow_html=True)

    page = st.radio(
        "Navigation",
        ["🏠 Overview", "📋 PR Analyses", "🔍 Incident Memory", "📈 Analytics", "⚙️ Audit Log"],
        label_visibility="collapsed"
    )

    st.markdown("---")

    # Auto-refresh toggle
    auto_refresh = st.toggle("Auto-refresh (5s)", value=True)
    if auto_refresh:
        refresh_rate = st.slider("Interval (s)", 3, 30, 5)
    else:
        refresh_rate = None

    st.markdown("---")

    # Quick stats in sidebar
    st.markdown('<div class="section-title">Quick Stats</div>', unsafe_allow_html=True)

    st.markdown(f"""
    <div style="font-size:0.8rem;color:#94a3b8;line-height:2.2;">
        PRs Today&nbsp;&nbsp;&nbsp;<span style="color:#f1f5f9;font-weight:600;">
            {safe_count('pr_analyses', {'timestamp': {'$gte': today_start}})}
        </span><br>
        Critical Today&nbsp;<span style="color:#ff4757;font-weight:600;">
            {safe_count('pr_analyses', {'timestamp': {'$gte': today_start}, 'risk_level': 'CRITICAL'})}
        </span><br>
        Agents Running&nbsp;<span style="color:#2ed573;font-weight:600;">5</span>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown('<div style="font-size:0.68rem;color:#334155;text-align:center;">v1.0.0 · Google Cloud Hackathon</div>',
                unsafe_allow_html=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AUTO-REFRESH
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if auto_refresh and refresh_rate:
    st.markdown(
        f'<meta http-equiv="refresh" content="{refresh_rate}">',
        unsafe_allow_html=True
    )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HELPER FUNCTIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def risk_badge(level: str) -> str:
    level = (level or "NONE").upper()
    cls = {"CRITICAL": "badge-critical", "HIGH": "badge-high",
           "LOW": "badge-low"}.get(level, "badge-none")
    icon = {"CRITICAL": "🔴", "HIGH": "🟡", "LOW": "🟢"}.get(level, "⚪")
    return f'<span class="badge {cls}">{icon} {level}</span>'


def risk_color(level: str) -> str:
    return {"CRITICAL": "#ff4757", "HIGH": "#ffa502", "LOW": "#2ed573"}.get(
        (level or "").upper(), "#94a3b8"
    )


def fmt_ts(ts) -> str:
    if isinstance(ts, datetime):
        return ts.strftime("%H:%M:%S")
    return str(ts)[:8] if ts else "—"


def fmt_dt(ts) -> str:
    if isinstance(ts, datetime):
        return ts.strftime("%b %d, %H:%M")
    return "—"


def hex_to_rgb(hex_color: str) -> str:
    """BUG FIX: Converts #rrggbb to 'r,g,b' string safely outside f-string."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"{r},{g},{b}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PAGE: OVERVIEW
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if "Overview" in page:

    # ── Hero header ───────────────────────────────────────────────
    st.markdown("""
    <div style="margin-bottom:2rem;">
        <h1 style="font-size:2rem;font-weight:800;color:#f1f5f9;margin:0;letter-spacing:-1px;">
            Production Safety Dashboard
        </h1>
        <p style="color:#64748b;margin-top:6px;font-size:0.9rem;">
            Real-time monitoring of your 5-agent pipeline · MongoDB Atlas + Gemini 2.5 Flash
        </p>
    </div>
    """, unsafe_allow_html=True)

    # ── KPI Cards ─────────────────────────────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)

    total_prs      = safe_count("pr_analyses")
    critical_count = safe_count("pr_analyses", {"risk_level": "CRITICAL"})
    # BUG FIX: was "pr_comment_posted" — correct action_type is "risk_comment_posted"
    prevented      = safe_count("audit_log", {"action_type": "risk_comment_posted"})
    incidents_mem  = safe_count("past_incidents")
    query_patterns = safe_count("query_patterns")

    today_prs      = safe_count("pr_analyses", {"timestamp": {"$gte": today_start}})
    today_critical = safe_count("pr_analyses", {"timestamp": {"$gte": today_start}, "risk_level": "CRITICAL"})

    with k1:
        st.metric("PRs Analysed", total_prs, f"+{today_prs} today")
    with k2:
        st.metric("🔴 Critical PRs", critical_count, f"+{today_critical} today", delta_color="inverse")
    with k3:
        st.metric("🛡️ Incidents Prevented", prevented, "+1 this week")
    with k4:
        st.metric("🧠 Incident Memory", incidents_mem, "6 seed incidents")
    with k5:
        st.metric("📊 Query Patterns", query_patterns)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Main layout: Left (live feed) + Right (chart) ─────────────
    left, right = st.columns([1.4, 1], gap="large")

    with left:
        st.markdown('<div class="section-title">⚡ Live Agent Activity Feed</div>', unsafe_allow_html=True)
        audit_logs = safe_find("audit_log", limit=12)

        if audit_logs:
            agent_icons = {
                "harvester": "🌾",
                "analyst": "🔍",
                "scale_tester": "⚡",
                "risk_narrator": "📝",
                "action_agent": "🚀"
            }
            for log in audit_logs:
                icon   = agent_icons.get(log.get("agent_name", ""), "🤖")
                action = log.get("action_type", "unknown").replace("_", " ")
                pr_id  = log.get("pr_id", "?")
                agent  = log.get("agent_name", "unknown")
                ts     = fmt_ts(log.get("timestamp"))
                details  = log.get("details", {})
                risk_lvl = details.get("risk_level", "")
                badge    = risk_badge(risk_lvl) if risk_lvl else ""

                st.markdown(f"""
                <div class="log-row">
                    <span style="font-size:1rem;">{icon}</span>
                    <span class="log-time">{ts}</span>
                    <span class="log-agent">{agent}</span>
                    <span style="color:#334155;font-size:0.9rem;">›</span>
                    <span class="log-action">{action}</span>
                    <span class="log-pr">PR #{pr_id}</span>
                    {badge}
                </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div class="glass-card" style="text-align:center;padding:2rem;">
                <div style="font-size:2rem;">🌾</div>
                <div style="color:#64748b;font-size:0.85rem;margin-top:0.5rem;">
                    Waiting for GitHub webhook events...
                </div>
            </div>
            """, unsafe_allow_html=True)

    with right:
        st.markdown('<div class="section-title">📊 Risk Distribution</div>', unsafe_allow_html=True)

        # Donut chart — risk level distribution
        crit = safe_count("pr_analyses", {"risk_level": "CRITICAL"})
        high = safe_count("pr_analyses", {"risk_level": "HIGH"})
        low  = safe_count("pr_analyses", {"risk_level": "LOW"})

        fig_donut = go.Figure(data=[go.Pie(
            labels=["CRITICAL", "HIGH", "LOW"],
            values=[crit or 0.001, high or 0.001, low or 0.001],
            hole=0.68,
            marker=dict(
                colors=["#ff4757", "#ffa502", "#2ed573"],
                line=dict(color="#080c14", width=3)
            ),
            textinfo="none",
            hovertemplate="<b>%{label}</b><br>%{value} PRs<br>%{percent}<extra></extra>"
        )])
        fig_donut.add_annotation(
            text=f"<b>{total_prs}</b><br><span style='font-size:11px'>PRs</span>",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=20, color="#f1f5f9", family="Inter")
        )
        fig_donut.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=0, b=0, l=0, r=0),
            height=240,
            showlegend=True,
            legend=dict(
                font=dict(color="#94a3b8", size=11, family="Inter"),
                bgcolor="rgba(0,0,0,0)",
                orientation="h",
                yanchor="bottom", y=-0.15,
                xanchor="center", x=0.5
            )
        )
        st.plotly_chart(fig_donut, use_container_width=True, config={"displayModeBar": False})

        # ── Mini agent pipeline status ─────────────────────────────
        st.markdown('<div class="section-title" style="margin-top:0.5rem;">🤖 Agent Pipeline</div>',
                    unsafe_allow_html=True)

        agents = [
            ("🌾", "Harvester",     "Monitors webhooks",       True),
            ("🔍", "Analyst",       "Vector Search ready",     True),
            ("⚡", "Scale Tester",  "Atlas connected",         True),
            ("📝", "Risk Narrator", "Gemini 2.5 Flash ready",  True),
            ("🚀", "Action Agent",  "GitHub token active",     True),
        ]
        for icon, name, status, active in agents:
            color = "#2ed573" if active else "#ff4757"
            dot = "●" if active else "○"
            st.markdown(f"""
            <div style="display:flex;align-items:center;gap:10px;
                        padding:7px 10px;border-radius:8px;margin-bottom:4px;
                        background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.04);">
                <span>{icon}</span>
                <span style="color:{color};font-size:0.65rem;">{dot}</span>
                <span style="color:#f1f5f9;font-size:0.82rem;font-weight:500;flex:1;">{name}</span>
                <span style="color:#475569;font-size:0.72rem;font-family:'JetBrains Mono',monospace;">{status}</span>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Recent PR Analyses table ───────────────────────────────────
    st.markdown('<div class="section-title">📋 Recent PR Analyses</div>', unsafe_allow_html=True)
    analyses = safe_find("pr_analyses", exclude=["embedding"], limit=6)

    if analyses:
        for a in analyses:
            risk      = a.get("risk_score") or 0
            level     = a.get("risk_level", "")
            title     = a.get("pr_title", "Unknown PR")
            # BUG FIX: truncate safely — don't use [:60] with hardcoded "..." in f-string
            title_short = (title[:78] + "…") if len(title) > 78 else title
            pr_id     = a.get("pr_id", "?")
            author    = a.get("pr_author", "—")
            ts        = fmt_dt(a.get("timestamp"))
            repo      = a.get("repo", "—")
            status    = a.get("status", "pending")
            score_pct = f"{risk:.0%}" if risk else "—"
            bar_w     = int(risk * 100)
            bar_color = "#ff4757" if level == "CRITICAL" else "#ffa502" if level == "HIGH" else "#2ed573"

            st.markdown(f"""
            <div class="pr-row">
                <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:1rem;">
                    <div style="flex:1;">
                        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                            {risk_badge(level)}
                            <span style="color:#64748b;font-size:0.72rem;font-family:'JetBrains Mono',monospace;">#{pr_id}</span>
                        </div>
                        <div class="pr-title">{title_short}</div>
                        <div class="pr-meta">@{author} · {repo} · {ts} · {status}</div>
                    </div>
                    <div style="text-align:right;min-width:80px;">
                        <div style="font-size:1.3rem;font-weight:700;color:{bar_color};">{score_pct}</div>
                        <div style="font-size:0.7rem;color:#475569;">risk score</div>
                        <div style="margin-top:6px;height:4px;background:#1e293b;border-radius:4px;width:80px;">
                            <div style="height:4px;border-radius:4px;width:{bar_w}%;background:{bar_color};
                                        box-shadow:0 0 8px {bar_color}40;"></div>
                        </div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="glass-card" style="text-align:center;padding:2.5rem;">
            <div style="font-size:2.5rem;margin-bottom:0.75rem;">📭</div>
            <div style="color:#64748b;">No PR analyses yet. Send a GitHub webhook to trigger the pipeline.</div>
        </div>
        """, unsafe_allow_html=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PAGE: PR ANALYSES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
elif "PR Analyses" in page:
    st.markdown("""
    <h1 style="font-size:1.8rem;font-weight:800;color:#f1f5f9;margin-bottom:0.3rem;">PR Analyses</h1>
    <p style="color:#64748b;font-size:0.85rem;margin-bottom:1.5rem;">
        Full history of every pull request processed by DevSentinel
    </p>
    """, unsafe_allow_html=True)

    # Filter bar
    f1, f2, f3 = st.columns([1, 1, 2])
    with f1:
        filter_risk = st.selectbox("Risk Level", ["All", "CRITICAL", "HIGH", "LOW"])
    with f2:
        filter_status = st.selectbox("Status", ["All", "complete", "analysed", "pending_analysis"])
    with f3:
        search_term = st.text_input("Search by title or author", placeholder="e.g. payment_status...")

    query = {}
    if filter_risk != "All":
        query["risk_level"] = filter_risk
    if filter_status != "All":
        query["status"] = filter_status

    analyses = safe_find("pr_analyses", query=query, exclude=["embedding"], limit=50)

    if search_term:
        search_lower = search_term.lower()
        analyses = [a for a in analyses if
                    search_lower in a.get("pr_title", "").lower() or
                    search_lower in a.get("pr_author", "").lower()]

    st.markdown(f'<div style="color:#64748b;font-size:0.8rem;margin-bottom:1rem;">'
                f'Showing {len(analyses)} results</div>', unsafe_allow_html=True)

    for a in analyses:
        risk   = a.get("risk_score") or 0
        level  = a.get("risk_level", "")
        pr_id  = a.get("pr_id", "?")
        title  = a.get("pr_title", "Unknown")
        author = a.get("pr_author", "—")
        repo   = a.get("repo", "—")
        ts     = fmt_dt(a.get("timestamp"))
        status = a.get("status", "pending")
        files  = len(a.get("files_changed", []))
        fields = ", ".join(a.get("mongo_fields_changed", [])[:4]) or "—"
        colls  = ", ".join(a.get("collections_mentioned", [])[:3]) or "—"
        incs   = len(a.get("matched_incidents", []))
        bar_color = "#ff4757" if level == "CRITICAL" else "#ffa502" if level == "HIGH" else "#2ed573"
        url    = a.get("pr_url", "#")
        # BUG FIX: safe truncation for expander label
        label_title = (title[:57] + "…") if len(title) > 57 else title

        with st.expander(f"PR #{pr_id} — {label_title}", expanded=False):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Risk Score", f"{risk:.0%}")
            c2.metric("Files Changed", files)
            c3.metric("Matched Incidents", incs)
            c4.metric("Status", status.replace("_", " ").title())

            schema_str = "Yes" if a.get("has_schema_change") else "No"
            query_str  = "Yes" if a.get("has_query_change") else "No"

            st.markdown(f"""
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin:1rem 0;">
                <div class="glass-card">
                    <div class="section-title">MongoDB Signals</div>
                    <div style="font-size:0.82rem;color:#94a3b8;line-height:2;">
                        Fields changed: <span style="color:#f1f5f9;">{fields}</span><br>
                        Collections: <span style="color:#f1f5f9;">{colls}</span><br>
                        Schema change: <span style="color:#f1f5f9;">{schema_str}</span><br>
                        Query change: <span style="color:#f1f5f9;">{query_str}</span>
                    </div>
                </div>
                <div class="glass-card">
                    <div class="section-title">PR Details</div>
                    <div style="font-size:0.82rem;color:#94a3b8;line-height:2;">
                        Author: <span style="color:#f1f5f9;">@{author}</span><br>
                        Repo: <span style="color:#f1f5f9;">{repo}</span><br>
                        Opened: <span style="color:#f1f5f9;">{ts}</span><br>
                        Risk level: {risk_badge(level)}
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # Index warnings
            idx_warnings = a.get("index_warnings", [])
            if idx_warnings:
                st.markdown('<div class="section-title">⚠️ Index Warnings</div>', unsafe_allow_html=True)
                for w in idx_warnings:
                    st.warning(w)

            if url and url != "#":
                st.markdown(f'<a href="{url}" target="_blank" style="color:#00d9ff;font-size:0.82rem;">→ View on GitHub</a>',
                            unsafe_allow_html=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PAGE: INCIDENT MEMORY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
elif "Incident Memory" in page:
    st.markdown("""
    <h1 style="font-size:1.8rem;font-weight:800;color:#f1f5f9;margin-bottom:0.3rem;">Incident Memory</h1>
    <p style="color:#64748b;font-size:0.85rem;margin-bottom:1.5rem;">
        Past incidents stored in MongoDB Atlas with Voyage AI embeddings — the "memory" for Vector Search
    </p>
    """, unsafe_allow_html=True)

    incidents = safe_find("past_incidents", exclude=["embedding"], limit=20)

    severity_colors = {"P0": "#ff4757", "P1": "#ffa502", "P2": "#ffd32a", "P3": "#2ed573"}

    if incidents:
        for inc in incidents:
            sev      = inc.get("severity", "P2")
            color    = severity_colors.get(sev, "#94a3b8")
            title    = inc.get("title", "Unknown Incident")
            desc     = inc.get("description", "")[:200]
            date     = inc.get("date", "—")
            recovery = inc.get("recovery_time_hours", "?")
            fix      = inc.get("fix_applied", "—")
            colls    = ", ".join(inc.get("collections_affected", []))
            services = ", ".join(inc.get("services_affected", []))
            lesson   = inc.get("lesson_learned", "")
            # BUG FIX: hex_to_rgb() pulled out of f-string — generators in f-strings cause SyntaxError
            rgb      = hex_to_rgb(color)

            st.markdown(f"""
            <div class="glass-card">
                <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:1rem;">
                    <div style="flex:1;">
                        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
                            <span style="background:rgba({rgb},0.15);
                                         color:{color};border:1px solid {color}40;
                                         padding:2px 10px;border-radius:20px;font-size:0.68rem;
                                         font-weight:700;letter-spacing:0.06em;">{sev}</span>
                            <span style="color:#64748b;font-size:0.75rem;font-family:'JetBrains Mono',monospace;">{date}</span>
                        </div>
                        <div style="font-size:1rem;font-weight:600;color:#f1f5f9;margin-bottom:6px;">{title}</div>
                        <div style="font-size:0.82rem;color:#94a3b8;line-height:1.6;">{desc}…</div>
                    </div>
                    <div style="text-align:right;min-width:120px;">
                        <div style="font-size:1.8rem;font-weight:700;color:{color};">{recovery}h</div>
                        <div style="font-size:0.7rem;color:#475569;">recovery time</div>
                    </div>
                </div>
                <div style="margin-top:1rem;display:grid;grid-template-columns:1fr 1fr 1fr;gap:1rem;
                            padding-top:1rem;border-top:1px solid rgba(255,255,255,0.05);">
                    <div>
                        <div style="font-size:0.65rem;color:#475569;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px;">Collections</div>
                        <div style="font-size:0.8rem;color:#94a3b8;font-family:'JetBrains Mono',monospace;">{colls or "—"}</div>
                    </div>
                    <div>
                        <div style="font-size:0.65rem;color:#475569;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px;">Fix Applied</div>
                        <div style="font-size:0.8rem;color:#2ed573;">{fix[:80]}</div>
                    </div>
                    <div>
                        <div style="font-size:0.65rem;color:#475569;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px;">Lesson</div>
                        <div style="font-size:0.78rem;color:#94a3b8;">{lesson[:80]}</div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="glass-card" style="text-align:center;padding:3rem;">
            <div style="font-size:3rem;margin-bottom:1rem;">🧠</div>
            <div style="color:#64748b;font-size:0.9rem;">
                No incidents seeded yet.<br>
                Run <code style="color:#00d9ff;">python migrations/seed_incidents.py</code> to populate memory.
            </div>
        </div>
        """, unsafe_allow_html=True)

    # Query patterns section
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="section-title">⚡ Stored Query Patterns</div>', unsafe_allow_html=True)
    qpatterns = safe_find("query_patterns", limit=8)

    if qpatterns:
        for qp in qpatterns:
            rl   = qp.get("risk_level", "")
            coll = qp.get("collection", "?")
            op   = qp.get("operation", "find")
            qt   = qp.get("query_text", "")[:80]
            idx  = qp.get("suggested_index", "—")
            ts   = fmt_dt(qp.get("timestamp"))

            st.markdown(f"""
            <div class="pr-row">
                <div style="display:flex;align-items:center;gap:10px;">
                    {risk_badge(rl)}
                    <span style="color:#00d9ff;font-family:'JetBrains Mono',monospace;font-size:0.78rem;">{coll}.{op}()</span>
                    <span style="color:#64748b;font-size:0.75rem;flex:1;">{qt}</span>
                    <span style="color:#475569;font-size:0.72rem;">{ts}</span>
                </div>
                <div style="margin-top:6px;padding-left:90px;font-size:0.75rem;color:#64748b;">
                    Suggested index: <code style="color:#7c3aed;">{idx}</code>
                </div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No query patterns stored yet — they appear when ScaleTester detects risky queries.")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PAGE: ANALYTICS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
elif "Analytics" in page:
    st.markdown("""
    <h1 style="font-size:1.8rem;font-weight:800;color:#f1f5f9;margin-bottom:0.3rem;">Analytics</h1>
    <p style="color:#64748b;font-size:0.85rem;margin-bottom:1.5rem;">
        Risk trends, collection heatmaps, and agent performance metrics
    </p>
    """, unsafe_allow_html=True)

    # BUG FIX: Load analyses_data ONCE at page level so both columns can access it
    analyses_data = safe_find("pr_analyses", exclude=["embedding", "files_changed",
                                                       "matched_incidents"], limit=200)

    row1_l, row1_r = st.columns(2, gap="large")

    # ── Chart 1: Risk score distribution histogram ─────────────────
    with row1_l:
        st.markdown('<div class="section-title">Risk Score Distribution</div>', unsafe_allow_html=True)
        if analyses_data:
            scores = [a.get("risk_score") or 0 for a in analyses_data]
            levels = [a.get("risk_level", "LOW") for a in analyses_data]

            df_scores = pd.DataFrame({"score": scores, "level": levels})
            color_map = {"CRITICAL": "#ff4757", "HIGH": "#ffa502", "LOW": "#2ed573", "None": "#475569"}

            fig_hist = px.histogram(
                df_scores, x="score", color="level",
                nbins=20,
                color_discrete_map=color_map,
                template="plotly_dark",
                labels={"score": "Risk Score", "count": "PRs"}
            )
            fig_hist.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=10, b=30, l=10, r=10),
                height=250,
                font=dict(family="Inter", color="#94a3b8"),
                legend=dict(font=dict(color="#94a3b8"), bgcolor="rgba(0,0,0,0)"),
                xaxis=dict(gridcolor="rgba(255,255,255,0.05)", tickformat=".0%"),
                yaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
                bargap=0.1
            )
            st.plotly_chart(fig_hist, use_container_width=True, config={"displayModeBar": False})
        else:
            st.markdown('<div class="glass-card" style="text-align:center;padding:3rem;color:#475569;">No data yet</div>',
                        unsafe_allow_html=True)

    # ── Chart 2: PRs over time ─────────────────────────────────────
    with row1_r:
        st.markdown('<div class="section-title">PR Volume Over Time</div>', unsafe_allow_html=True)
        if analyses_data:
            dates = []
            for a in analyses_data:
                ts = a.get("timestamp")
                if isinstance(ts, datetime):
                    dates.append(ts.date())

            if dates:
                df_time = pd.DataFrame({"date": dates})
                df_time = df_time.groupby("date").size().reset_index(name="count")

                fig_line = go.Figure()
                fig_line.add_trace(go.Scatter(
                    x=df_time["date"], y=df_time["count"],
                    mode="lines+markers",
                    line=dict(color="#00d9ff", width=2.5, shape="spline"),
                    marker=dict(color="#00d9ff", size=6),
                    fill="tozeroy",
                    fillcolor="rgba(0,217,255,0.07)",
                    name="PRs"
                ))
                fig_line.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(t=10, b=30, l=10, r=10),
                    height=250,
                    font=dict(family="Inter", color="#94a3b8"),
                    showlegend=False,
                    xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
                    yaxis=dict(gridcolor="rgba(255,255,255,0.05)")
                )
                st.plotly_chart(fig_line, use_container_width=True, config={"displayModeBar": False})
            else:
                st.info("Need timestamped data to show trends.")
        else:
            st.markdown('<div class="glass-card" style="text-align:center;padding:3rem;color:#475569;">No data yet</div>',
                        unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    row2_l, row2_r = st.columns(2, gap="large")

    # ── Chart 3: Top risky collections bar chart ───────────────────
    with row2_l:
        st.markdown('<div class="section-title">Top Risky Collections</div>', unsafe_allow_html=True)
        if analyses_data:
            all_colls = []
            for a in analyses_data:
                all_colls.extend(a.get("collections_mentioned", []))

            if all_colls:
                coll_counts = Counter(all_colls).most_common(8)
                df_colls = pd.DataFrame(coll_counts, columns=["collection", "count"])

                fig_bar = go.Figure(go.Bar(
                    x=df_colls["count"],
                    y=df_colls["collection"],
                    orientation="h",
                    marker=dict(
                        color=df_colls["count"],
                        colorscale=[[0, "#7c3aed"], [0.5, "#00d9ff"], [1, "#ff4757"]],
                        line=dict(width=0)
                    ),
                    hovertemplate="<b>%{y}</b><br>%{x} PRs<extra></extra>"
                ))
                fig_bar.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(t=10, b=10, l=10, r=10),
                    height=260,
                    font=dict(family="Inter", color="#94a3b8"),
                    xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
                    yaxis=dict(gridcolor="rgba(255,255,255,0.0)")
                )
                st.plotly_chart(fig_bar, use_container_width=True, config={"displayModeBar": False})
            else:
                st.info("No collections data yet.")
        else:
            st.info("No analyses data.")

    # ── Chart 4: Agent action breakdown ───────────────────────────
    with row2_r:
        st.markdown('<div class="section-title">Agent Action Breakdown</div>', unsafe_allow_html=True)
        all_logs = safe_find("audit_log", limit=200)

        if all_logs:
            agent_counts = Counter(log.get("agent_name", "unknown") for log in all_logs)
            agents_list  = list(agent_counts.keys())
            counts_list  = list(agent_counts.values())

            # BUG FIX: guard against more agents than colors
            palette = ["#2ed573", "#00d9ff", "#ffa502", "#7c3aed", "#ff4757"]
            colors  = [palette[i % len(palette)] for i in range(len(agents_list))]

            fig_agents = go.Figure(go.Bar(
                x=agents_list,
                y=counts_list,
                marker=dict(color=colors, line=dict(width=0)),
                hovertemplate="<b>%{x}</b><br>%{y} actions<extra></extra>"
            ))
            fig_agents.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=10, b=10, l=10, r=10),
                height=260,
                font=dict(family="Inter", color="#94a3b8"),
                xaxis=dict(gridcolor="rgba(255,255,255,0.0)"),
                yaxis=dict(gridcolor="rgba(255,255,255,0.05)")
            )
            st.plotly_chart(fig_agents, use_container_width=True, config={"displayModeBar": False})
        else:
            st.markdown('<div class="glass-card" style="text-align:center;padding:3rem;color:#475569;">No agent activity yet</div>',
                        unsafe_allow_html=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PAGE: AUDIT LOG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
elif "Audit" in page:
    st.markdown("""
    <h1 style="font-size:1.8rem;font-weight:800;color:#f1f5f9;margin-bottom:0.3rem;">Audit Log</h1>
    <p style="color:#64748b;font-size:0.85rem;margin-bottom:1.5rem;">
        Every agent action, immutably recorded in MongoDB for compliance and debugging
    </p>
    """, unsafe_allow_html=True)

    # Stats row
    s1, s2, s3 = st.columns(3)
    s1.metric("Total Audit Events", safe_count("audit_log"))
    # BUG FIX: today_start now defined at module level — no NameError on this page
    s2.metric("Today's Events", safe_count("audit_log", {"timestamp": {"$gte": today_start}}))
    s3.metric("Change Requests", safe_count("change_requests"))

    st.markdown("<br>", unsafe_allow_html=True)

    all_logs = safe_find("audit_log", limit=100)

    # Action type filter
    action_types = list(set(log.get("action_type", "") for log in all_logs if log.get("action_type")))
    selected_action = st.selectbox("Filter by Action", ["All"] + sorted(action_types))

    if selected_action != "All":
        all_logs = [l for l in all_logs if l.get("action_type") == selected_action]

    for log in all_logs:
        ts       = fmt_dt(log.get("timestamp"))
        action   = log.get("action_type", "unknown")
        agent    = log.get("agent_name", "unknown")
        pr_id    = log.get("pr_id", "—")
        details  = log.get("details", {})
        risk_lvl = details.get("risk_level", "")
        badge_html = risk_badge(risk_lvl) if risk_lvl else ""
        # BUG FIX: build score string outside f-string to avoid complex conditional expressions
        score_val = details.get("risk_score")
        score_str = f"· score: {score_val}" if score_val else ""

        agent_icon = {
            "harvester": "🌾", "analyst": "🔍", "scale_tester": "⚡",
            "risk_narrator": "📝", "action_agent": "🚀"
        }.get(agent, "🤖")

        st.markdown(f"""
        <div class="log-row" style="padding:0.8rem 1rem;">
            <span style="font-size:1.1rem;">{agent_icon}</span>
            <div style="flex:1;">
                <div style="display:flex;align-items:center;gap:8px;">
                    <span class="log-agent" style="font-size:0.8rem;">{agent}</span>
                    <span style="color:#334155;">›</span>
                    <span class="log-action" style="font-size:0.82rem;">{action.replace("_", " ")}</span>
                    {badge_html}
                </div>
                <div style="font-size:0.72rem;color:#475569;margin-top:3px;font-family:'JetBrains Mono',monospace;">
                    PR #{pr_id} · {ts} {score_str}
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    if not all_logs:
        st.markdown("""
        <div class="glass-card" style="text-align:center;padding:3rem;">
            <div style="font-size:2rem;margin-bottom:0.5rem;">📋</div>
            <div style="color:#64748b;">No audit events recorded yet.</div>
        </div>
        """, unsafe_allow_html=True)
