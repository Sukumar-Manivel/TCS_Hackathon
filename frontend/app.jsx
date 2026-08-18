const { useState, useEffect, useCallback, useMemo } = React;

const DEFAULT_API_BASE = (() => {
  const params = new URLSearchParams(window.location.search);
  if (params.get("api")) return params.get("api");
  if (window.location.protocol === "file:") return "http://127.0.0.1:8000";
  return window.location.origin.replace(/:\d+$/, ":8000");
})();

function useApi(apiBase) {
  const call = useCallback(
    async (path, options = {}) => {
      const res = await fetch(apiBase + path, {
        headers: { "Content-Type": "application/json" },
        ...options,
      });
      let body = null;
      try {
        body = await res.json();
      } catch (e) {
        body = null;
      }
      if (!res.ok) {
        const detail = (body && body.detail) || res.statusText;
        throw new Error(detail);
      }
      return body;
    },
    [apiBase]
  );
  return call;
}

const PRIORITY_COLORS = {
  Critical: "#C4432B",
  High: "#E8A33D",
  Medium: "#4FA3B0",
  Low: "#6B7480",
};

const STATUS_LABELS = {
  pending_review: "Awaiting review",
  approved: "Approved · in progress",
  rejected: "Dismissed",
  resolved: "Resolved",
  needs_reanalysis: "Reopened · needs reanalysis",
};

function EvidenceBar({ label, strength, metric, evidence }) {
  const pct = Math.round(strength * 100);
  return (
    <div className="evidence-row">
      <div className="evidence-row-top">
        <span className="evidence-hypothesis">{label}</span>
        <span className="evidence-pct">{pct}%</span>
      </div>
      <div className="evidence-track">
        <div
          className="evidence-fill"
          style={{ width: pct + "%", background: pct >= 60 ? "#E8A33D" : "#4B5563" }}
        />
      </div>
      <div className="evidence-caption">{evidence}</div>
    </div>
  );
}

function StatusStamp({ status }) {
  const map = {
    resolved: { text: "RESOLVED", color: "#3E8E7E" },
    rejected: { text: "DISMISSED", color: "#8A8377" },
    needs_reanalysis: { text: "REOPENED", color: "#C4432B" },
  };
  const cfg = map[status];
  if (!cfg) return null;
  return (
    <div className="stamp" style={{ borderColor: cfg.color, color: cfg.color }}>
      {cfg.text}
    </div>
  );
}

function StatBlock({ label, value, accent }) {
  return (
    <div className="stat-block">
      <div className="stat-value" style={accent ? { color: accent } : undefined}>
        {value}
      </div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

function CaseCard({ issue, selected, onSelect }) {
  const color = PRIORITY_COLORS[issue.priority_label] || "#6B7480";
  return (
    <button className={"case-card" + (selected ? " case-card--selected" : "")} onClick={() => onSelect(issue.issue_id)}>
      <div className="case-card-row">
        <span className="case-id">{issue.issue_id}</span>
        <span className="case-score" style={{ color }}>
          {issue.priority_score}
        </span>
      </div>
      <div className="case-title">{issue.label}</div>
      <div className="case-meta">
        <span className="badge" style={{ borderColor: color, color }}>
          {issue.priority_label}
        </span>
        <span className="case-meta-text">
          {issue.feedback_count} exhibits · {issue.channels.length} channels
        </span>
      </div>
      <div className="case-status">{STATUS_LABELS[issue.status] || issue.status}</div>
    </button>
  );
}

function CaseDetail({ issue, apiBase, api, onChanged, notice }) {
  const [owner, setOwner] = useState(issue.owner || "");
  const [notes, setNotes] = useState("");
  const [modifiedAction, setModifiedAction] = useState("");
  const [showOutcomeForm, setShowOutcomeForm] = useState(false);
  const [beforeVal, setBeforeVal] = useState(issue.intervention.kpi_current ?? "");
  const [afterVal, setAfterVal] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setOwner(issue.owner || issue.intervention.owner || "");
    setBeforeVal(issue.intervention.kpi_current ?? "");
    setAfterVal("");
    setShowOutcomeForm(false);
  }, [issue.issue_id]);

  const decide = async (decision) => {
    setBusy(true);
    try {
      await api("/validate", {
        method: "POST",
        body: JSON.stringify({
          issue_id: issue.issue_id,
          decision,
          owner,
          notes,
          modified_action: decision === "modified" ? modifiedAction : undefined,
        }),
      });
      await onChanged(`Case ${issue.issue_id} marked ${decision}.`);
    } catch (e) {
      await onChanged("Error: " + e.message, true);
    } finally {
      setBusy(false);
    }
  };

  const submitOutcome = async () => {
    setBusy(true);
    try {
      await api("/outcomes", {
        method: "POST",
        body: JSON.stringify({
          issue_id: issue.issue_id,
          kpi_name: issue.intervention.kpi_name,
          before_value: parseFloat(beforeVal),
          after_value: parseFloat(afterVal),
          target_value: issue.intervention.kpi_target,
        }),
      });
      await onChanged(`Outcome recorded for ${issue.issue_id}.`);
      setShowOutcomeForm(false);
    } catch (e) {
      await onChanged("Error: " + e.message, true);
    } finally {
      setBusy(false);
    }
  };

  const color = PRIORITY_COLORS[issue.priority_label] || "#6B7480";
  const canValidate = issue.status === "pending_review" || issue.status === "needs_reanalysis";
  const canReportOutcome = issue.status === "approved";

  return (
    <div className="case-detail">
      <StatusStamp status={issue.status} />
      <div className="case-detail-header">
        <div className="eyebrow">Case file · {issue.issue_id}</div>
        <h2>{issue.label}</h2>
        <div className="case-detail-tags">
          <span className="badge" style={{ borderColor: color, color }}>
            {issue.priority_label} · {issue.priority_score}/100
          </span>
          <span className="pill">{issue.journey}</span>
          <span className="pill">{issue.feature}</span>
        </div>
      </div>

      <section className="section">
        <div className="section-title">Priority breakdown</div>
        <div className="score-grid">
          <div>
            <div className="score-num">{issue.priority_breakdown.customer_impact}</div>
            <div className="score-lbl">Customer impact</div>
          </div>
          <div>
            <div className="score-num">{issue.priority_breakdown.business_impact}</div>
            <div className="score-lbl">Business impact</div>
          </div>
          <div>
            <div className="score-num">{issue.priority_breakdown.recurrence_score}</div>
            <div className="score-lbl">Recurrence</div>
          </div>
          <div>
            <div className="score-num">{issue.priority_breakdown.evidence_confidence}</div>
            <div className="score-lbl">Evidence confidence</div>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="section-title">Exhibits — customer evidence ({issue.channels.join(", ")})</div>
        <ul className="exhibit-list">
          {issue.evidence_sample.map((text, idx) => (
            <li key={idx}>&ldquo;{text}&rdquo;</li>
          ))}
        </ul>
      </section>

      <section className="section">
        <div className="section-title">Root-cause hypotheses, ranked by evidence strength</div>
        {issue.root_causes.map((rc, idx) => (
          <EvidenceBar
            key={idx}
            label={rc.hypothesis}
            strength={rc.evidence_strength}
            metric={rc.metric}
            evidence={rc.supporting_evidence}
          />
        ))}
      </section>

      <section className="section">
        <div className="section-title">Recommended intervention</div>
        <div className="intervention-box">
          <p>{issue.intervention.recommended_action}</p>
          <div className="intervention-meta">
            <div>
              <span className="meta-key">Owner</span>
              <span className="meta-val">{issue.intervention.owner}</span>
            </div>
            <div>
              <span className="meta-key">KPI</span>
              <span className="meta-val">{issue.intervention.kpi_name}</span>
            </div>
            <div>
              <span className="meta-key">Current</span>
              <span className="meta-val">{issue.intervention.kpi_current ?? "—"}</span>
            </div>
            <div>
              <span className="meta-key">Target</span>
              <span className="meta-val">{issue.intervention.kpi_target ?? "—"}</span>
            </div>
          </div>
        </div>
      </section>

      {canValidate && (
        <section className="section">
          <div className="section-title">Human validation</div>
          <div className="form-row">
            <label>Owner</label>
            <input value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="Assign a team" />
          </div>
          <div className="form-row">
            <label>Notes</label>
            <input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Optional review notes" />
          </div>
          <div className="form-row">
            <label>Modify action (optional)</label>
            <input
              value={modifiedAction}
              onChange={(e) => setModifiedAction(e.target.value)}
              placeholder="Override the recommended action"
            />
          </div>
          <div className="button-row">
            <button className="btn btn-approve" disabled={busy} onClick={() => decide("approved")}>
              Approve
            </button>
            <button
              className="btn btn-modify"
              disabled={busy || !modifiedAction}
              onClick={() => decide("modified")}
            >
              Approve with changes
            </button>
            <button className="btn btn-reject" disabled={busy} onClick={() => decide("rejected")}>
              Reject
            </button>
          </div>
        </section>
      )}

      {canReportOutcome && (
        <section className="section">
          <div className="section-title">Outcome monitoring</div>
          {!showOutcomeForm ? (
            <button className="btn btn-outline" onClick={() => setShowOutcomeForm(true)}>
              Report outcome
            </button>
          ) : (
            <div>
              <div className="form-row">
                <label>KPI</label>
                <input value={issue.intervention.kpi_name} disabled />
              </div>
              <div className="form-row form-row-split">
                <div>
                  <label>Before</label>
                  <input value={beforeVal} onChange={(e) => setBeforeVal(e.target.value)} />
                </div>
                <div>
                  <label>After</label>
                  <input value={afterVal} onChange={(e) => setAfterVal(e.target.value)} placeholder="Observed value" />
                </div>
              </div>
              <div className="button-row">
                <button className="btn btn-approve" disabled={busy || afterVal === ""} onClick={submitOutcome}>
                  Submit outcome
                </button>
                <button className="btn btn-outline" disabled={busy} onClick={() => setShowOutcomeForm(false)}>
                  Cancel
                </button>
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function IngestPanel({ api, onIngested, notice }) {
  const [open, setOpen] = useState(false);
  const [channel, setChannel] = useState("app_review");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try {
      await api("/ingest", {
        method: "POST",
        body: JSON.stringify({ feedback: [{ channel, text }], operational_metrics: [] }),
      });
      setText("");
      await onIngested("Feedback ingested. Run analysis to fold it into the backlog.");
    } catch (e) {
      await onIngested("Error: " + e.message, true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <button className="panel-toggle" onClick={() => setOpen(!open)}>
        {open ? "▾" : "▸"} Add feedback manually
      </button>
      {open && (
        <div className="panel-body">
          <div className="form-row">
            <label>Channel</label>
            <select value={channel} onChange={(e) => setChannel(e.target.value)}>
              <option value="app_review">App review</option>
              <option value="support_ticket">Support ticket</option>
              <option value="survey">Survey</option>
              <option value="email">Email</option>
              <option value="social">Social</option>
            </select>
          </div>
          <div className="form-row">
            <label>Text</label>
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} />
          </div>
          <button className="btn btn-approve" disabled={busy || !text.trim()} onClick={submit}>
            Ingest
          </button>
        </div>
      )}
    </div>
  );
}

function App() {
  const [apiBase] = useState(DEFAULT_API_BASE);
  const api = useApi(apiBase);

  const [connected, setConnected] = useState(null);
  const [dashboard, setDashboard] = useState(null);
  const [backlog, setBacklog] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [toast, setToast] = useState(null);
  const [loadingAnalysis, setLoadingAnalysis] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [db, bl] = await Promise.all([api("/dashboard"), api("/backlog")]);
      setDashboard(db);
      setBacklog(bl.backlog);
      setConnected(true);
    } catch (e) {
      setConnected(false);
    }
  }, [api]);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 8000);
    return () => clearInterval(interval);
  }, [refresh]);

  const showToast = async (message, isError) => {
    setToast({ message, isError: !!isError });
    await refresh();
    setTimeout(() => setToast(null), 3500);
  };

  const seed = async () => {
    try {
      await api("/seed", { method: "POST" });
      await showToast("Demo dataset loaded — 17 feedback items, 13 operational metrics.");
    } catch (e) {
      await showToast("Error: " + e.message, true);
    }
  };

  const runAnalysis = async () => {
    setLoadingAnalysis(true);
    try {
      const res = await api("/analyze", { method: "POST" });
      await showToast(`Analysis complete — ${res.issues_created_or_updated} case(s) updated.`);
    } catch (e) {
      await showToast("Error: " + e.message, true);
    } finally {
      setLoadingAnalysis(false);
    }
  };

  const resetAll = async () => {
    try {
      await api("/reset", { method: "POST" });
      setSelectedId(null);
      await showToast("Store cleared.");
    } catch (e) {
      await showToast("Error: " + e.message, true);
    }
  };

  const selectedIssue = useMemo(
    () => backlog.find((i) => i.issue_id === selectedId) || null,
    [backlog, selectedId]
  );

  useEffect(() => {
    if (!selectedId && backlog.length > 0) setSelectedId(backlog[0].issue_id);
  }, [backlog, selectedId]);

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <div className="brand-mark">EB</div>
          <div>
            <div className="brand-title">Evidence Board</div>
            <div className="brand-sub">Customer intelligence → root cause → prioritized action</div>
          </div>
        </div>
        <div className="header-actions">
          <span className={"conn-dot " + (connected ? "conn-ok" : connected === false ? "conn-bad" : "")} />
          <span className="conn-label">{apiBase}</span>
          <button className="btn btn-outline" onClick={seed}>
            Load demo data
          </button>
          <button className="btn btn-approve" disabled={loadingAnalysis} onClick={runAnalysis}>
            {loadingAnalysis ? "Analyzing…" : "Run analysis"}
          </button>
          <button className="btn btn-reject" onClick={resetAll}>
            Reset
          </button>
        </div>
      </header>

      {connected === false && (
        <div className="banner banner-error">
          Can't reach the API at <code>{apiBase}</code>. Start the backend (see README) or add
          <code>?api=http://host:port</code> to the URL.
        </div>
      )}

      {dashboard && (
        <div className="stats-row">
          <StatBlock label="Total feedback" value={dashboard.total_feedback} />
          <StatBlock label="Open cases" value={dashboard.total_issues - dashboard.resolved_issue_count} />
          <StatBlock label="Critical" value={dashboard.critical_issue_count} accent={PRIORITY_COLORS.Critical} />
          <StatBlock label="Recurring" value={dashboard.recurring_issue_count} />
          <StatBlock label="Resolved" value={dashboard.resolved_issue_count} accent="#3E8E7E" />
          <StatBlock label="Analysis runs" value={dashboard.analysis_runs} />
        </div>
      )}

      <IngestPanel api={api} onIngested={showToast} />

      <div className="main-grid">
        <div className="backlog-col">
          <div className="section-title">Priority backlog</div>
          {backlog.length === 0 && (
            <div className="empty-state">
              No cases yet. Click <strong>Load demo data</strong>, then <strong>Run analysis</strong>.
            </div>
          )}
          {backlog.map((issue) => (
            <CaseCard key={issue.issue_id} issue={issue} selected={issue.issue_id === selectedId} onSelect={setSelectedId} />
          ))}
        </div>
        <div className="detail-col">
          {selectedIssue ? (
            <CaseDetail issue={selectedIssue} apiBase={apiBase} api={api} onChanged={showToast} />
          ) : (
            <div className="empty-state">Select a case from the backlog to view its evidence file.</div>
          )}
        </div>
      </div>

      {toast && <div className={"toast " + (toast.isError ? "toast-error" : "")}>{toast.message}</div>}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
