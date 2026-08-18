"""
FastAPI API gateway.

Frontend (React) never talks to LangGraph directly — it only ever calls
these REST endpoints, which invoke the compiled LangGraph pipeline and
persist results in the in-memory store.
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from models import IngestPayload, ValidationDecision, OutcomeReport, ChatRequest
from store import STORE, now_iso, kpi_direction_is_lower_better
from graph import run_analysis
from sample_data import SAMPLE_FEEDBACK, SAMPLE_OPERATIONAL_METRICS

app = FastAPI(
    title="Customer Intelligence Platform API",
    description="Evidence-driven customer feedback -> root cause -> prioritized action pipeline.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/seed")
def seed_demo_data():
    """Loads a ready-made demo dataset so the app can be demoed instantly."""
    STORE.reset()
    STORE.add_feedback(SAMPLE_FEEDBACK)
    STORE.add_operational_metrics(SAMPLE_OPERATIONAL_METRICS)
    return {
        "feedback_ingested": len(STORE.feedback),
        "metrics_ingested": len(STORE.operational_metrics),
    }


@app.post("/reset")
def reset_all():
    STORE.reset()
    return {"status": "reset"}


@app.post("/ingest")
def ingest(payload: IngestPayload):
    added_feedback = STORE.add_feedback([f.model_dump() for f in payload.feedback])
    STORE.add_operational_metrics([m.model_dump() for m in payload.operational_metrics])
    return {
        "feedback_ingested": len(added_feedback),
        "metrics_ingested": len(payload.operational_metrics),
        "total_feedback": len(STORE.feedback),
    }


@app.post("/analyze")
def analyze():
    """Runs the LangGraph pipeline: issue discovery -> root cause ->
    evidence testing -> prioritization -> intervention."""
    if not STORE.feedback:
        raise HTTPException(status_code=400, detail="No feedback ingested yet. Call /ingest or /seed first.")
    issues = run_analysis()
    return {
        "issues_created_or_updated": len(issues),
        "backlog_size": len(STORE.backlog),
        "issues": issues,
    }


@app.get("/issues")
def list_issues():
    return {"issues": list(STORE.issues.values())}


@app.get("/issues/{issue_id}")
def get_issue(issue_id: str):
    issue = STORE.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return issue


@app.get("/backlog")
def get_backlog():
    return {"backlog": STORE.backlog}


@app.get("/dashboard")
def dashboard():
    issues = list(STORE.issues.values())
    critical = [i for i in issues if i["priority_label"] == "Critical" and i["status"] not in ("resolved", "rejected")]
    resolved = [i for i in issues if i["status"] == "resolved"]
    recurring = [i for i in issues if i["feedback_count"] >= 2]
    return {
        "total_feedback": len(STORE.feedback),
        "total_issues": len(issues),
        "critical_issue_count": len(critical),
        "recurring_issue_count": len(recurring),
        "resolved_issue_count": len(resolved),
        "analysis_runs": STORE.analysis_runs,
        "top_issues": STORE.backlog[:5],
    }


@app.post("/validate")
def validate(decision: ValidationDecision):
    issue = STORE.get_issue(decision.issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    if decision.decision == "approved":
        issue["status"] = "approved"
    elif decision.decision == "modified":
        issue["status"] = "approved"
        if decision.modified_action:
            issue["intervention"]["recommended_action"] = decision.modified_action
    elif decision.decision == "rejected":
        issue["status"] = "rejected"

    issue["owner"] = decision.owner or issue.get("owner") or issue["intervention"].get("owner")
    issue["validation_notes"] = decision.notes
    issue["updated_at"] = now_iso()
    STORE.upsert_issue(issue)
    STORE.rebuild_backlog()
    return issue


@app.post("/outcomes")
def report_outcome(report: OutcomeReport):
    issue = STORE.get_issue(report.issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue["status"] != "approved":
        raise HTTPException(status_code=400, detail="Issue must be approved before reporting an outcome.")

    lower_is_better = kpi_direction_is_lower_better(issue["issue_key"], report.kpi_name)
    if lower_is_better:
        improved = report.after_value < report.before_value
    else:
        improved = report.after_value > report.before_value

    outcome = {
        "outcome_id": f"OUT-{len(STORE.outcomes) + 1}",
        "issue_id": report.issue_id,
        "kpi_name": report.kpi_name,
        "before_value": report.before_value,
        "after_value": report.after_value,
        "target_value": report.target_value,
        "improved": improved,
        "reported_at": report.reported_at or now_iso(),
    }
    STORE.outcomes.append(outcome)

    if improved:
        issue["status"] = "resolved"
    else:
        issue["status"] = "needs_reanalysis"
        # Feed the failure back in: bump the issue's priority slightly so it
        # resurfaces near the top of the backlog for re-investigation.
        issue["priority_score"] = min(100.0, issue["priority_score"] + 5)
        issue["priority_label"] = issue["priority_label"]
    issue["updated_at"] = now_iso()
    STORE.upsert_issue(issue)
    STORE.rebuild_backlog()

    return {"outcome": outcome, "issue_status": issue["status"]}


@app.get("/outcomes")
def list_outcomes():
    return {"outcomes": STORE.outcomes}

@app.post("/api/chat")
def chat_endpoint(request: ChatRequest):
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY environment variable is not set. Please set it to use the AI assistant.")
        
    issues = list(STORE.issues.values())
    case_context = "\n".join(
        f"- {i['issue_id']}: '{i['label']}' (Status: {i['status']}, Priority Score: {i.get('priority_score', 0)})" 
        for i in issues
    )
    if not case_context:
        case_context = "No active cases."
        
    system_prompt = f"""You are the Evidence Board AI assistant, embedded in a customer intelligence dashboard. 
You help a product/support team understand feedback, root causes and prioritization. 
Be concise, direct, and practical — a few short sentences or a tight list, not long essays. 
Here is the current case data:
{case_context}"""

    messages = [{"role": "system", "content": system_prompt}]
    for msg in request.messages:
        messages.append({"role": msg.role, "content": msg.content})

    data = json.dumps({
        "model": "anthropic/claude-3-haiku",
        "messages": messages,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    )
    
    try:
        with urllib.request.urlopen(req) as resp:
            resp_body = resp.read()
            resp_json = json.loads(resp_body)
            reply = resp_json["choices"][0]["message"]["content"]
            return {"reply": reply}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print("OpenRouter Error:", error_body)
        raise HTTPException(status_code=502, detail=f"Error from OpenRouter: {e.reason}")
    except Exception as e:
        print("Chat Error:", str(e))
        raise HTTPException(status_code=500, detail="An error occurred communicating with OpenRouter.")
