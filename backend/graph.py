"""
LangGraph orchestration for the analysis pipeline.

Shared state flows through:
  issue_discovery -> root_cause_analysis -> evidence_testing
  -> prioritization -> intervention_agent -> END

Each node reads from and writes to the shared TypedDict state, matching the
architecture: LangGraph owns sequencing/state, deterministic Python owns
scoring, and the "LLM slot" (classify_feedback / evaluate_hypotheses) is
isolated in store.py so it can be swapped for a real LLM call later without
touching the graph wiring.
"""
from __future__ import annotations

from typing import Dict, List, TypedDict

from langgraph.graph import StateGraph, END

from store import (
    STORE,
    ISSUE_TAXONOMY,
    GENERAL_ISSUE_KEY,
    classify_feedback,
    evaluate_hypotheses,
    compute_priority,
    build_intervention,
    new_id,
    now_iso,
)


class PipelineState(TypedDict, total=False):
    feedback: List[dict]
    clusters: Dict[str, List[dict]]
    issue_records: List[dict]


def issue_discovery(state: PipelineState) -> PipelineState:
    feedback = state["feedback"]
    clusters: Dict[str, List[dict]] = {}
    for item in feedback:
        key = classify_feedback(item["text"])
        clusters.setdefault(key, []).append(item)
    state["clusters"] = clusters
    return state


def root_cause_and_evidence(state: PipelineState) -> PipelineState:
    """Combines the Root Cause Agent + Evidence Testing step: for every
    cluster, generate hypotheses and score them against operational data."""
    records = []
    for issue_key, items in state["clusters"].items():
        root_causes = evaluate_hypotheses(issue_key)
        records.append({
            "issue_key": issue_key,
            "items": items,
            "root_causes": root_causes,
        })
    state["issue_records"] = records
    return state


def prioritization(state: PipelineState) -> PipelineState:
    total_feedback = len(state["feedback"])
    for record in state["issue_records"]:
        top_strength = record["root_causes"][0]["evidence_strength"] if record["root_causes"] else 0.0
        record["priority"] = compute_priority(
            record["issue_key"], record["items"], total_feedback, top_strength
        )
    return state


def intervention_agent(state: PipelineState) -> PipelineState:
    for record in state["issue_records"]:
        record["intervention"] = build_intervention(record["issue_key"], record["root_causes"])
    return state


def build_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("issue_discovery", issue_discovery)
    graph.add_node("root_cause_and_evidence", root_cause_and_evidence)
    graph.add_node("prioritization", prioritization)
    graph.add_node("intervention_agent", intervention_agent)

    graph.set_entry_point("issue_discovery")
    graph.add_edge("issue_discovery", "root_cause_and_evidence")
    graph.add_edge("root_cause_and_evidence", "prioritization")
    graph.add_edge("prioritization", "intervention_agent")
    graph.add_edge("intervention_agent", END)

    return graph.compile()


COMPILED_GRAPH = build_graph()


def run_analysis() -> List[dict]:
    """Runs the compiled LangGraph pipeline over everything currently in the
    store, then persists the results as Issue records and rebuilds the
    priority backlog. Returns the list of issues touched by this run."""
    if not STORE.feedback:
        return []

    result_state = COMPILED_GRAPH.invoke({"feedback": STORE.feedback})
    STORE.analysis_runs += 1

    touched_issues = []
    for record in result_state["issue_records"]:
        issue_key = record["issue_key"]
        label = ISSUE_TAXONOMY.get(issue_key, {}).get("label", "General Feedback")
        journey = ISSUE_TAXONOMY.get(issue_key, {}).get("journey", "Unclassified")
        feature = ISSUE_TAXONOMY.get(issue_key, {}).get("feature", "Unclassified")

        # Re-use an existing issue id for this issue_key if one is already
        # open, so repeated /analyze runs update rather than duplicate.
        existing = next(
            (i for i in STORE.issues.values()
             if i["issue_key"] == issue_key and i["status"] not in ("resolved", "rejected")),
            None,
        )
        issue_id = existing["issue_id"] if existing else new_id("ISSUE")

        channels = sorted({i["channel"] for i in record["items"]})
        issue = {
            "issue_id": issue_id,
            "issue_key": issue_key,
            "label": label,
            "journey": journey,
            "feature": feature,
            "channels": channels,
            "feedback_count": len(record["items"]),
            "recurrence": round(len(record["items"]) / len(STORE.feedback), 3),
            "evidence_sample": [i["text"] for i in record["items"][:3]],
            "root_causes": record["root_causes"],
            "priority_score": record["priority"]["priority_score"],
            "priority_label": record["priority"]["priority_label"],
            "priority_breakdown": record["priority"],
            "intervention": record["intervention"],
            "status": existing["status"] if existing else "pending_review",
            "owner": existing.get("owner") if existing else None,
            "validation_notes": existing.get("validation_notes") if existing else None,
            "updated_at": now_iso(),
            "created_at": existing["created_at"] if existing else now_iso(),
        }
        STORE.upsert_issue(issue)
        touched_issues.append(issue)

    STORE.rebuild_backlog()
    return touched_issues
