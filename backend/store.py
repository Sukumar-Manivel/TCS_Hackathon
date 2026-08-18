"""
In-memory data store + the deterministic "business logic" layer.

Per the architecture:
  - The LLM/graph layer handles clustering *reasoning* (here approximated with
    transparent keyword matching so the demo runs with zero external API keys).
  - This module handles everything that should be deterministic: scoring,
    thresholds, aggregation and persistence.
"""
from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Issue taxonomy: the "domain knowledge" the Issue Discovery / Root Cause
# agents draw on. Each entry maps a problem type to the keywords that signal
# it, the operational metrics that would corroborate it, and a templated
# intervention.
# ---------------------------------------------------------------------------
ISSUE_TAXONOMY: Dict[str, dict] = {
    "payment_failure": {
        "label": "Payment Failure",
        "journey": "Checkout",
        "feature": "Payments",
        "keywords": [
            "payment", "checkout", "transaction", "charge", "card declined",
            "pay", "billing failed", "gateway",
        ],
        "hypotheses": [
            {"name": "Payment API latency spike", "metric": "payment_api_latency_ms"},
            {"name": "Payment gateway timeout errors", "metric": "gateway_timeout_rate"},
            {"name": "Mobile app payment bug", "metric": None},
        ],
        "intervention": "Implement retry logic with an automatic fallback payment gateway and add a circuit breaker for timeout handling.",
        "owner": "Payments Engineering",
        "kpi_name": "payment_success_rate",
        "kpi_metric": "payment_success_rate",
        "kpi_higher_is_better": True,
    },
    "login_failure": {
        "label": "Login / Authentication Failure",
        "journey": "Account Access",
        "feature": "Authentication",
        "keywords": [
            "login", "log in", "sign in", "password", "authentication",
            "locked out", "otp", "verification code", "2fa",
        ],
        "hypotheses": [
            {"name": "Auth service latency", "metric": "auth_latency_ms"},
            {"name": "OTP delivery failures", "metric": "otp_delivery_failure_rate"},
            {"name": "User error / weak onboarding copy", "metric": None},
        ],
        "intervention": "Optimize the authentication service call path and add a fallback OTP delivery channel (SMS -> email).",
        "owner": "Identity & Access Team",
        "kpi_name": "login_success_rate",
        "kpi_metric": "login_success_rate",
        "kpi_higher_is_better": True,
    },
    "delivery_delay": {
        "label": "Delivery Delay",
        "journey": "Post-Purchase",
        "feature": "Fulfilment",
        "keywords": [
            "delivery", "shipping", "late", "delayed", "not received",
            "courier", "shipment", "arrived late",
        ],
        "hypotheses": [
            {"name": "Warehouse dispatch bottleneck", "metric": "warehouse_dispatch_hours"},
            {"name": "Courier SLA breaches", "metric": "courier_sla_breach_rate"},
            {"name": "Address / logistics data errors", "metric": None},
        ],
        "intervention": "Rebalance warehouse inventory allocation and renegotiate SLAs with underperforming courier partners.",
        "owner": "Operations",
        "kpi_name": "on_time_delivery_rate",
        "kpi_metric": "on_time_delivery_rate",
        "kpi_higher_is_better": True,
    },
    "app_crash": {
        "label": "App Crash / Stability",
        "journey": "In-App Usage",
        "feature": "Mobile App Stability",
        "keywords": [
            "crash", "freeze", "force close", "not responding", "glitch",
            "app closes", "stuck loading",
        ],
        "hypotheses": [
            {"name": "Elevated crash rate in latest release", "metric": "crash_rate"},
            {"name": "Unhandled client-side errors", "metric": "client_error_rate"},
            {"name": "Device / OS compatibility issue", "metric": None},
        ],
        "intervention": "Fast-track a stability hotfix release and expand automated crash triage / alerting.",
        "owner": "Mobile Engineering",
        "kpi_name": "crash_free_sessions_rate",
        "kpi_metric": "crash_free_sessions_rate",
        "kpi_higher_is_better": True,
    },
    "support_experience": {
        "label": "Support Responsiveness",
        "journey": "Customer Support",
        "feature": "Support Operations",
        "keywords": [
            "support", "no response", "no reply", "agent", "customer service",
            "long wait", "ticket", "on hold",
        ],
        "hypotheses": [
            {"name": "Rising average response time", "metric": "avg_response_time_hours"},
            {"name": "Ticket backlog growth", "metric": "ticket_backlog_count"},
            {"name": "Under-staffing for demand", "metric": None},
        ],
        "intervention": "Add surge staffing / triage automation for the support queue and set an SLA-based escalation rule.",
        "owner": "Customer Support",
        "kpi_name": "avg_first_response_time_hours",
        "kpi_metric": "avg_response_time_hours",
        "kpi_higher_is_better": False,
    },
    "ui_ux_confusion": {
        "label": "Confusing UI / UX",
        "journey": "General Usage",
        "feature": "Product UX",
        "keywords": [
            "confusing", "hard to use", "difficult to navigate", "cluttered",
            "cannot find", "ui is bad", "not intuitive",
        ],
        "hypotheses": [
            {"name": "High drop-off on a specific flow", "metric": "flow_drop_off_rate"},
            {"name": "Unclear information architecture", "metric": None},
        ],
        "intervention": "Run a usability study on the flagged flow and simplify the navigation / information hierarchy.",
        "owner": "Product Design",
        "kpi_name": "task_completion_rate",
        "kpi_metric": "flow_drop_off_rate",
        "kpi_higher_is_better": True,
    },
    "pricing_billing": {
        "label": "Pricing / Billing Complaint",
        "journey": "Billing",
        "feature": "Billing",
        "keywords": [
            "expensive", "overcharged", "refund", "billing", "double charged",
            "hidden fee", "price increase",
        ],
        "hypotheses": [
            {"name": "Billing calculation errors", "metric": "billing_error_rate"},
            {"name": "Unclear pricing communication", "metric": None},
        ],
        "intervention": "Audit the billing pipeline for calculation errors and clarify pricing/fees in-product before checkout.",
        "owner": "Finance / Billing",
        "kpi_name": "billing_dispute_rate",
        "kpi_metric": "billing_error_rate",
        "kpi_higher_is_better": False,
    },
    "performance_slow": {
        "label": "Slow Performance",
        "journey": "General Usage",
        "feature": "Platform Performance",
        "keywords": [
            "slow", "lag", "laggy", "loading forever", "buffering",
            "takes forever", "unresponsive",
        ],
        "hypotheses": [
            {"name": "Elevated page/API latency", "metric": "api_latency_ms"},
            {"name": "Unoptimized client rendering", "metric": None},
        ],
        "intervention": "Run a performance optimization sprint (query tuning + caching layer) targeting the slowest endpoints.",
        "owner": "Platform Engineering",
        "kpi_name": "p95_latency_ms",
        "kpi_metric": "api_latency_ms",
        "kpi_higher_is_better": False,
    },
}

GENERAL_ISSUE_KEY = "general_feedback"


# ---------------------------------------------------------------------------
# In-memory "database"
# ---------------------------------------------------------------------------
class Store:
    def __init__(self) -> None:
        self.feedback: List[dict] = []
        self.operational_metrics: Dict[str, dict] = {}
        self.issues: Dict[str, dict] = {}       # issue_id -> issue record
        self.backlog: List[dict] = []           # ordered priority backlog (issue_ids, refreshed on analyze)
        self.outcomes: List[dict] = []
        self.analysis_runs: int = 0

    def reset(self) -> None:
        self.__init__()

    # -- ingestion ----------------------------------------------------
    def add_feedback(self, items: List[dict]) -> List[dict]:
        added = []
        for item in items:
            item = dict(item)
            item["id"] = item.get("id") or new_id("FB")
            item["timestamp"] = item.get("timestamp") or now_iso()
            self.feedback.append(item)
            added.append(item)
        return added

    def add_operational_metrics(self, metrics: List[dict]) -> None:
        for m in metrics:
            self.operational_metrics[m["name"]] = dict(m)

    # -- issue helpers --------------------------------------------------
    def upsert_issue(self, issue: dict) -> dict:
        self.issues[issue["issue_id"]] = issue
        return issue

    def get_issue(self, issue_id: str) -> Optional[dict]:
        return self.issues.get(issue_id)

    def rebuild_backlog(self) -> None:
        active = [i for i in self.issues.values() if i["status"] not in ("resolved", "rejected")]
        active.sort(key=lambda i: i["priority_score"], reverse=True)
        self.backlog = active


STORE = Store()


# ---------------------------------------------------------------------------
# Scoring helpers (deterministic — the LLM never sets these numbers directly)
# ---------------------------------------------------------------------------
def classify_feedback(text: str) -> str:
    """Keyword-based cross-channel issue classification.

    This stands in for the Issue Discovery agent's semantic clustering step
    so the app runs end-to-end with zero external API keys. If an
    OPENAI_API_KEY / compatible LLM is configured (see llm.py), this can be
    swapped for a real semantic classification without changing callers.
    """
    text_l = text.lower()
    best_key, best_score = GENERAL_ISSUE_KEY, 0
    for key, spec in ISSUE_TAXONOMY.items():
        score = sum(1 for kw in spec["keywords"] if kw in text_l)
        if score > best_score:
            best_key, best_score = key, score
    return best_key


def pct_change(baseline: float, current: float) -> float:
    if baseline == 0:
        return 0.0 if current == 0 else 1.0
    return (current - baseline) / baseline


def evaluate_hypotheses(issue_key: str) -> List[dict]:
    """Root Cause Agent + Evidence Testing, combined.

    Generates hypotheses from the taxonomy, then tests each one against
    ingested operational metrics. Hypotheses backed by real metric deviation
    score higher; hypotheses with no corroborating data get a low, capped
    confidence so the LLM can't unilaterally claim high confidence.
    """
    spec = ISSUE_TAXONOMY.get(issue_key)
    if not spec:
        return [{
            "hypothesis": "Uncategorized issue — insufficient signal to hypothesize a root cause",
            "metric": None,
            "evidence_strength": 0.15,
            "supporting_evidence": "No taxonomy match; recommend manual triage.",
        }]

    results = []
    for hyp in spec["hypotheses"]:
        metric_name = hyp["metric"]
        metric = STORE.operational_metrics.get(metric_name) if metric_name else None
        if metric:
            change = pct_change(metric["baseline"], metric["current"])
            strength = max(0.0, min(1.0, abs(change)))
            evidence = (
                f"{metric_name} moved from {metric['baseline']} to {metric['current']} "
                f"{metric.get('unit', '')} ({change * 100:+.1f}%)"
            ).strip()
        else:
            strength = 0.25  # weak default: no operational data to corroborate
            evidence = "No corroborating operational metric ingested for this hypothesis."
        results.append({
            "hypothesis": hyp["name"],
            "metric": metric_name,
            "evidence_strength": round(strength, 2),
            "supporting_evidence": evidence,
        })

    results.sort(key=lambda r: r["evidence_strength"], reverse=True)
    return results


def priority_label(score: float) -> str:
    if score >= 85:
        return "Critical"
    if score >= 70:
        return "High"
    if score >= 50:
        return "Medium"
    return "Low"


def compute_priority(issue_key: str, cluster_items: List[dict], total_feedback: int,
                      top_evidence_strength: float) -> dict:
    n = len(cluster_items)
    freq_ratio = n / total_feedback if total_feedback else 0
    channels = {i["channel"] for i in cluster_items}
    channel_diversity = min(1.0, len(channels) / 3)

    customer_impact = min(100.0, (0.7 * freq_ratio * 100) + (0.3 * channel_diversity * 100))
    business_impact = min(100.0, top_evidence_strength * 100)
    recurrence_score = min(100.0, freq_ratio * 130)
    evidence_confidence = min(100.0, top_evidence_strength * 100)

    score = round(
        0.35 * customer_impact
        + 0.30 * business_impact
        + 0.20 * recurrence_score
        + 0.15 * evidence_confidence,
        1,
    )
    return {
        "priority_score": score,
        "priority_label": priority_label(score),
        "customer_impact": round(customer_impact, 1),
        "business_impact": round(business_impact, 1),
        "recurrence_score": round(recurrence_score, 1),
        "evidence_confidence": round(evidence_confidence, 1),
    }


def build_intervention(issue_key: str, root_causes: List[dict]) -> dict:
    spec = ISSUE_TAXONOMY.get(issue_key)
    top_cause = root_causes[0] if root_causes else None
    if not spec:
        return {
            "recommended_action": "Route to manual triage — no taxonomy match found.",
            "owner": "Product Ops",
            "kpi_name": "n/a",
            "kpi_current": None,
            "kpi_target": None,
        }

    kpi_metric = STORE.operational_metrics.get(spec.get("kpi_metric"))
    kpi_current = kpi_metric["current"] if kpi_metric else None
    kpi_target = None
    if kpi_current is not None:
        # crude but transparent heuristic: aim to close ~80% of the gap to baseline
        baseline = kpi_metric["baseline"]
        kpi_target = round(kpi_current + 0.8 * (baseline - kpi_current), 2)

    return {
        "recommended_action": spec["intervention"],
        "owner": spec["owner"],
        "kpi_name": spec["kpi_name"],
        "kpi_current": kpi_current,
        "kpi_target": kpi_target,
        "based_on_root_cause": top_cause["hypothesis"] if top_cause else None,
    }


def kpi_direction_is_lower_better(issue_key: str, kpi_name: str) -> bool:
    """Determines whether a lower KPI value counts as an improvement.

    Primary source of truth: the explicit `kpi_higher_is_better` flag on the
    matched taxonomy entry (set per-KPI, not guessed from the name — e.g.
    'on_time_delivery_rate' contains the substring 'time' but is very much a
    higher-is-better metric, so name-sniffing alone is unreliable).

    Falls back to a conservative keyword heuristic only when the KPI name
    doesn't match any known taxonomy KPI (e.g. a custom KPI supplied by the
    caller for an ad-hoc / general issue).
    """
    spec = ISSUE_TAXONOMY.get(issue_key)
    if spec and spec.get("kpi_name") == kpi_name and "kpi_higher_is_better" in spec:
        return not spec["kpi_higher_is_better"]

    # Fallback heuristic for unmapped KPI names, using whole-word matching
    # to avoid substring false-positives like "time" inside "on_time".
    name_words = set(kpi_name.lower().replace("-", "_").split("_"))
    lower_is_better_words = {"latency", "error", "errors", "backlog", "dispute", "disputes", "delay", "delays", "breach", "breaches"}
    return bool(name_words & lower_is_better_words)
