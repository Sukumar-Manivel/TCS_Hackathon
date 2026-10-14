"""
FastAPI API gateway.

Frontend (React) never talks to LangGraph directly — it only ever calls
these REST endpoints, which invoke the compiled LangGraph pipeline and
persist results in the in-memory store.
"""
from __future__ import annotations

import csv
import io
import json
import os
import urllib.request
import urllib.error
from typing import List, Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware

# Simple .env parser to support the frontend/.env file
env_path = os.path.join(os.path.dirname(__file__), "../frontend/.env")
if os.path.exists(env_path):
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k] = v

from models import IngestPayload, ValidationDecision, OutcomeReport, ChatRequest, normalize_channel
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
def ingest(payload: IngestPayload, auto_analyze: bool = Query(True, description="Automatically run LangGraph analysis after ingestion")):
    added_feedback = STORE.add_feedback([f.model_dump() for f in payload.feedback])
    STORE.add_operational_metrics([m.model_dump() for m in payload.operational_metrics])
    
    issues = []
    if auto_analyze and STORE.feedback:
        issues = run_analysis()

    return {
        "feedback_ingested": len(added_feedback),
        "metrics_ingested": len(payload.operational_metrics),
        "total_feedback": len(STORE.feedback),
        "auto_analyzed": bool(issues),
        "issues_created_or_updated": len(issues),
        "backlog_size": len(STORE.backlog),
        "issues": issues,
    }


def parse_uploaded_file_data(filename: str, content_bytes: bytes) -> tuple[list[dict], list[dict]]:
    try:
        content_str = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content_str = content_bytes.decode("latin-1", errors="ignore")

    feedback_items: list[dict] = []
    metrics_items: list[dict] = []
    filename_lower = filename.lower()

    # 1. Try parsing JSON
    if filename_lower.endswith(".json") or content_str.strip().startswith(("{", "[")):
        try:
            data = json.loads(content_str)
            if isinstance(data, dict):
                if "feedback" in data and isinstance(data["feedback"], list):
                    for item in data["feedback"]:
                        if isinstance(item, dict) and "text" in item:
                            feedback_items.append({
                                "text": str(item["text"]),
                                "channel": normalize_channel(item.get("channel")),
                                "customer_id": item.get("customer_id"),
                                "category": item.get("category"),
                                "timestamp": item.get("timestamp"),
                            })
                        elif isinstance(item, str):
                            feedback_items.append({"channel": "survey", "text": item})
                if "operational_metrics" in data and isinstance(data["operational_metrics"], list):
                    for m in data["operational_metrics"]:
                        if isinstance(m, dict) and "name" in m and "baseline" in m and "current" in m:
                            metrics_items.append({
                                "name": str(m["name"]),
                                "baseline": float(m["baseline"]),
                                "current": float(m["current"]),
                                "unit": str(m.get("unit", "")),
                            })
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        text = item.get("text") or item.get("comment") or item.get("feedback") or item.get("message")
                        if text:
                            feedback_items.append({
                                "text": str(text),
                                "channel": normalize_channel(item.get("channel")),
                                "customer_id": item.get("customer_id") or item.get("user_id"),
                                "category": item.get("category"),
                                "timestamp": item.get("timestamp"),
                            })
                        elif "baseline" in item and "current" in item and "name" in item:
                            metrics_items.append({
                                "name": str(item["name"]),
                                "baseline": float(item["baseline"]),
                                "current": float(item["current"]),
                                "unit": str(item.get("unit", "")),
                            })
                    elif isinstance(item, str) and item.strip():
                        feedback_items.append({"channel": "survey", "text": item.strip()})
            return feedback_items, metrics_items
        except Exception:
            pass

    # 2. Try parsing CSV
    if filename_lower.endswith(".csv") or "," in content_str:
        try:
            reader = csv.DictReader(io.StringIO(content_str))
            for row in reader:
                if not row:
                    continue
                row_norm = {str(k).strip().lower(): (str(v).strip() if v is not None else "") for k, v in row.items() if k}
                
                # Check for operational metric
                if ("name" in row_norm or "metric" in row_norm) and ("baseline" in row_norm and "current" in row_norm):
                    try:
                        name = row_norm.get("name") or row_norm.get("metric")
                        metrics_items.append({
                            "name": name,
                            "baseline": float(row_norm["baseline"]),
                            "current": float(row_norm["current"]),
                            "unit": row_norm.get("unit", "")
                        })
                        continue
                    except ValueError:
                        pass
                
                # Check for feedback text
                text = (
                    row_norm.get("text") or
                    row_norm.get("feedback") or
                    row_norm.get("comment") or
                    row_norm.get("review") or
                    row_norm.get("message") or
                    row_norm.get("content") or
                    row_norm.get("description") or
                    row_norm.get("issue")
                )
                if not text:
                    # fallback to first column with text
                    vals = [v for v in row.values() if v and len(str(v).strip()) > 3]
                    if vals:
                        text = vals[0]
                
                if text:
                    channel = normalize_channel(row_norm.get("channel") or row_norm.get("source") or row_norm.get("type"))
                    cust_id = row_norm.get("customer_id") or row_norm.get("user_id") or row_norm.get("id") or None
                    ts = row_norm.get("timestamp") or row_norm.get("date") or None
                    cat = row_norm.get("category") or None
                    feedback_items.append({
                        "text": str(text),
                        "channel": channel,
                        "customer_id": cust_id,
                        "category": cat,
                        "timestamp": ts
                    })
            if feedback_items or metrics_items:
                return feedback_items, metrics_items
        except Exception:
            pass

    # 3. Fallback: treat as plain text line-by-line
    lines = [l.strip() for l in content_str.splitlines() if l.strip()]
    for line in lines:
        feedback_items.append({"channel": "survey", "text": line})

    return feedback_items, metrics_items


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    auto_analyze: bool = Query(True, description="Automatically run LangGraph analysis after ingestion")
):
    """Uploads a feedback file (JSON, CSV, TXT), ingests it into the platform,
    and runs the LangGraph analysis pipeline."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    feedback_items, metrics_items = parse_uploaded_file_data(file.filename, content)
    if not feedback_items and not metrics_items:
        raise HTTPException(status_code=400, detail="Could not extract any feedback or metrics from uploaded file.")

    added_feedback = STORE.add_feedback(feedback_items)
    STORE.add_operational_metrics(metrics_items)

    issues = []
    if auto_analyze and STORE.feedback:
        issues = run_analysis()

    return {
        "filename": file.filename,
        "feedback_ingested": len(added_feedback),
        "metrics_ingested": len(metrics_items),
        "total_feedback": len(STORE.feedback),
        "auto_analyzed": bool(issues),
        "issues_created_or_updated": len(issues),
        "backlog_size": len(STORE.backlog),
        "issues": issues,
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
        "model": os.getenv("MODEL_NAME", "anthropic/claude-3-haiku"),
        "messages": messages,
        "max_tokens": 2000,
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
