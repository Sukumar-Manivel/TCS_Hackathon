"""
In-memory data store + the deterministic "business logic" layer.

Per the architecture:
  - The Issue Discovery agent clusters raw feedback with BERTopic and then
    interprets each topic against ISSUE_TAXONOMY to resolve it to a business
    issue_key (see discover_issue_clusters below). It falls back to
    transparent per-item keyword matching (classify_feedback) for outliers,
    small batches, or if BERTopic isn't installed, so the app always runs
    end-to-end with zero external API keys.
  - This module handles everything that should be deterministic: scoring,
    thresholds, aggregation and persistence.
"""
from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# BERTopic is an optional dependency: the Issue Discovery agent below uses it
# when available (and when there's enough feedback to form real clusters),
# and transparently falls back to the deterministic keyword classifier
# otherwise, so the app keeps running with zero external services/API keys.
# NOTE: we deliberately pass BERTopic a lightweight in-process TF-IDF + SVD
# embedder (see _TfidfEmbedder below) instead of its default
# sentence-transformers backend, so this stays free of a torch/HF download.
try:
    from bertopic import BERTopic
    from bertopic.backend import BaseEmbedder
    from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
    from sklearn.decomposition import TruncatedSVD
    from hdbscan import HDBSCAN
    from umap import UMAP

    _BERTOPIC_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised when optional deps absent
    _BERTOPIC_AVAILABLE = False


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
    """Keyword-based single-item issue classification.

    This is the deterministic fallback used by discover_issue_clusters()
    below: per-topic-outlier items, and the whole pipeline when there isn't
    enough feedback to cluster or BERTopic isn't installed, get labeled this
    way. Kept as its own function (rather than inlined) so it can still be
    called standalone, and so it can be swapped for a real LLM call later
    without touching callers.
    """
    text_l = text.lower()
    best_key, best_score = GENERAL_ISSUE_KEY, 0
    for key, spec in ISSUE_TAXONOMY.items():
        score = sum(1 for kw in spec["keywords"] if kw in text_l)
        if score > best_score:
            best_key, best_score = key, score
    return best_key


# ---------------------------------------------------------------------------
# Issue Discovery agent: BERTopic clustering + interpretation.
#
#   feedback -> BERTopic -> raw topic clusters (topic_0, topic_1, ...)
#            -> interpretation step: for each topic, look at its top
#               c-TF-IDF keywords + a few representative docs and match them
#               against the ISSUE_TAXONOMY vocabulary
#            -> business issue_key (payment_failure, login_failure, ...)
#            -> state["clusters"]
#
# BERTopic tells you *that* feedback items are similar; it never tells you
# *what the topic means* in taxonomy terms (it hands back "topic_3", not
# "payment_failure"). The interpretation step below is what closes that gap,
# so downstream nodes (root cause, prioritization, intervention) keep
# operating on the same taxonomy keys they always have.
# ---------------------------------------------------------------------------

# BERTopic/HDBSCAN need a reasonable number of documents to find real
# clusters; below this, fall back straight to per-item keyword
# classification rather than let the model manufacture noisy topics out of a
# handful of docs.
MIN_DOCS_FOR_TOPIC_MODEL = 15

# Minimum interpretation score (see _match_topic_to_issue) for a topic to be
# assigned a taxonomy issue_key. Topics that don't clear this bar are
# treated the same as BERTopic outliers: routed to per-item fallback instead
# of being forced into a taxonomy bucket they don't actually match.
TOPIC_MATCH_MIN_SCORE = 2.0


class _TfidfEmbedder(BaseEmbedder if _BERTOPIC_AVAILABLE else object):
    """Lightweight in-process embedding backend for BERTopic.

    Swaps out BERTopic's default sentence-transformers backend (which
    downloads a model and pulls in torch) for a TF-IDF + truncated-SVD
    embedding fit on the batch itself. This keeps the Issue Discovery agent
    fully offline/local, consistent with the rest of the app's "zero
    external API keys" design.
    """

    def __init__(self, n_components: int = 15):
        super().__init__()
        self.n_components = n_components
        self._vectorizer: Optional["TfidfVectorizer"] = None
        self._svd: Optional["TruncatedSVD"] = None

    def embed(self, documents, verbose: bool = False):
        docs = list(documents)
        if self._vectorizer is None:
            # Unigrams + sublinear TF scaling produce a denser, less sparse
            # feature space than unigrams+bigrams on short feedback text,
            # which empirically gives HDBSCAN cleaner separation on small
            # batches. Topic *labeling* (get_topic()) still uses the richer
            # bigram vectorizer_model passed to BERTopic separately, so
            # phrase-level keywords like "card declined" are preserved there.
            self._vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 1), min_df=1, sublinear_tf=True)
            tfidf = self._vectorizer.fit_transform(docs)
            n_components = max(2, min(self.n_components, tfidf.shape[1] - 1, tfidf.shape[0] - 1))
            self._svd = TruncatedSVD(n_components=n_components, random_state=42)
            return self._svd.fit_transform(tfidf)
        tfidf = self._vectorizer.transform(docs)
        return self._svd.transform(tfidf)


_sentence_embedder = None
_sentence_embedder_checked = False


def _get_embedding_model():
    """Prefers real sentence-transformer embeddings (much better semantic
    clustering than TF-IDF) when the model is already available locally;
    transparently falls back to the offline _TfidfEmbedder otherwise so
    Issue Discovery never hard-depends on a model download / torch / a GPU.
    Checked once per process and cached.
    """
    global _sentence_embedder, _sentence_embedder_checked
    if _sentence_embedder_checked:
        return _sentence_embedder if _sentence_embedder is not None else _TfidfEmbedder(n_components=15)

    _sentence_embedder_checked = True
    try:
        from sentence_transformers import SentenceTransformer
        _sentence_embedder = SentenceTransformer("all-MiniLM-L6-v2")
    except Exception:
        _sentence_embedder = None
    return _sentence_embedder if _sentence_embedder is not None else _TfidfEmbedder(n_components=15)


def _build_topic_model(n_docs: int) -> "BERTopic":
    """Constructs a BERTopic instance with parameters scaled to the size of
    the batch being clustered, since HDBSCAN/UMAP defaults tuned for large
    corpora produce degenerate clusters (or crash outright) on small ones."""
    min_cluster_size = max(3, n_docs // 10)
    n_neighbors = max(2, min(10, n_docs // 4))
    n_components = max(2, min(5, n_docs // 6))

    return BERTopic(
        embedding_model=_get_embedding_model(),
        vectorizer_model=CountVectorizer(stop_words="english", ngram_range=(1, 2), min_df=1),
        umap_model=UMAP(n_neighbors=n_neighbors, n_components=n_components, min_dist=0.0, random_state=42),
        hdbscan_model=HDBSCAN(min_cluster_size=min_cluster_size, min_samples=1),
        calculate_probabilities=False,
        verbose=False,
    )


def _match_topic_to_issue(topic_keywords: List[str], sample_texts: List[str]) -> Tuple[str, float]:
    """Interpretation step: decides which business issue (if any) a BERTopic
    topic corresponds to.

    Reuses the same taxonomy keyword vocabulary classify_feedback() draws
    on, so a topic's meaning is grounded in the same domain knowledge as the
    rest of the app instead of an opaque embedding similarity score. Topic
    keyword hits are weighted higher than sample-document hits, since they
    summarize the whole cluster rather than just the first few items in it.
    """
    joined_keywords = " ".join(topic_keywords).lower()
    sample_blob = " ".join(sample_texts).lower()

    best_key, best_score = GENERAL_ISSUE_KEY, 0.0
    for key, spec in ISSUE_TAXONOMY.items():
        keyword_hits = sum(1 for kw in spec["keywords"] if kw in joined_keywords)
        text_hits = sum(1 for kw in spec["keywords"] if kw in sample_blob)
        score = (2.0 * keyword_hits) + (1.0 * text_hits)
        if score > best_score:
            best_key, best_score = key, score
    return best_key, best_score


def _keyword_cluster(feedback: List[dict]) -> Dict[str, List[dict]]:
    """Per-item keyword clustering: the original classify_feedback-per-item
    approach, used as the fallback when BERTopic isn't available or there's
    too little feedback to form real topic clusters."""
    clusters: Dict[str, List[dict]] = {}
    for item in feedback:
        key = classify_feedback(item["text"])
        clusters.setdefault(key, []).append(item)
    return clusters


def discover_issue_clusters(feedback: List[dict]) -> Dict[str, List[dict]]:
    """Issue Discovery agent: BERTopic clustering + interpretation.

    1. Cluster feedback into topics with BERTopic (topic_0, topic_1, ...).
    2. Interpret each topic: match its top keywords + a few representative
       docs against ISSUE_TAXONOMY to resolve it to a business issue_key.
    3. Anything BERTopic can't confidently place — outlier docs (topic -1)
       and topics whose interpretation score doesn't clear
       TOPIC_MATCH_MIN_SCORE — falls back to per-item keyword
       classification instead of being dropped or mis-bucketed.

    Falls back to pure per-item keyword clustering entirely when BERTopic
    isn't installed, or when there's too little feedback
    (< MIN_DOCS_FOR_TOPIC_MODEL) for topic modeling to be meaningful.

    Returns the same Dict[issue_key, List[feedback_item]] shape the graph's
    downstream nodes (root cause, prioritization, intervention) already
    expect, so nothing beyond this function needs to change.
    """
    if not _BERTOPIC_AVAILABLE or len(feedback) < MIN_DOCS_FOR_TOPIC_MODEL:
        return _keyword_cluster(feedback)

    texts = [item["text"] for item in feedback]
    try:
        model = _build_topic_model(len(texts))
        topics, _ = model.fit_transform(texts)
    except Exception:
        # Any topic-modeling failure (degenerate embeddings, clustering
        # errors, etc.) should degrade gracefully rather than break analysis.
        return _keyword_cluster(feedback)

    clusters: Dict[str, List[dict]] = {}
    fallback_items: List[dict] = []

    for topic_id in sorted(set(topics)):
        idxs = [i for i, t in enumerate(topics) if t == topic_id]
        items = [feedback[i] for i in idxs]

        if topic_id == -1:
            fallback_items.extend(items)
            continue

        topic_words = [w for w, _ in (model.get_topic(topic_id) or [])]
        sample_texts = [it["text"] for it in items[:5]]
        issue_key, score = _match_topic_to_issue(topic_words, sample_texts)

        if score < TOPIC_MATCH_MIN_SCORE:
            fallback_items.extend(items)
            continue

        clusters.setdefault(issue_key, []).extend(items)

    # Best-effort per-item classification for anything the topic model
    # couldn't confidently place, so no feedback silently disappears.
    for item in fallback_items:
        issue_key = classify_feedback(item["text"])
        clusters.setdefault(issue_key, []).append(item)

    return clusters


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