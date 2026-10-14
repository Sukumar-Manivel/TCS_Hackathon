# Evidence Board — Customer Intelligence Platform

An evidence-driven customer feedback pipeline: ingest feedback from multiple
channels → cluster into cross-channel issues → generate root-cause
hypotheses and test them against operational metrics → compute a
transparent priority score → recommend an intervention → route it through
human validation → monitor the outcome and reopen the case automatically if
the fix didn't work.

```
React (single HTML file)  --REST/JSON-->  FastAPI  --invoke()-->  LangGraph pipeline
                                              |
                                       in-memory store
```

This matches the architecture:

```
issue_discovery -> root_cause_and_evidence -> prioritization -> intervention_agent
```

wired as an actual `langgraph.graph.StateGraph`. The graph nodes are
deterministic Python (keyword-based clustering + metric-deviation scoring)
so the **whole app runs end-to-end with zero API keys** — nothing to sign up
for, nothing that can silently fail during a demo. The clustering/hypothesis
step (`classify_feedback` / `evaluate_hypotheses` in `backend/store.py`) is
intentionally isolated so it can be swapped for a real LLM call later
without touching the graph wiring or the API.

## Quick start

### 1. Backend (FastAPI + LangGraph)

Requires **Python 3.10+** (tested on 3.12).

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

The API is now live at `http://127.0.0.1:8000`. Interactive docs at
`http://127.0.0.1:8000/docs`.

Pinned, tested-compatible versions (installing anything looser can break —
newer `langgraph` releases have changed the `StateGraph` API in
incompatible ways, and `fastapi`/`pydantic` major versions must line up):

```
fastapi==0.115.0
uvicorn[standard]==0.32.0
pydantic==2.9.2
langgraph==0.2.39
python-multipart==0.0.9
```

### 2. Frontend (React, no build step)

Just open `frontend/index.html` in a browser — or serve it so paths and
CORS behave identically to a real deployment:

```bash
cd frontend
python3 -m http.server 5500
```

Then visit `http://127.0.0.1:5500`. The frontend loads React, ReactDOM and
Babel Standalone from a CDN and compiles the single `app.jsx` file in the
browser at load time — **no `npm install`, no bundler, nothing to get
version-mismatched.**

By default the frontend calls the API at `http://127.0.0.1:8000`. If your
backend runs elsewhere, open the page with `?api=http://host:port`, e.g.
`http://127.0.0.1:5500/index.html?api=http://localhost:9000`.

### 3. Demo it

1. Click **Load demo data** (17 sample feedback items across app reviews,
   support tickets, surveys and email, plus 13 operational metrics).
2. Click **Run analysis** — this invokes the LangGraph pipeline and
   populates the priority backlog.
3. Click into a case to see its evidence exhibits, ranked root-cause
   hypotheses (with the operational metric that corroborates or fails to
   corroborate each one), and the recommended intervention.
4. **Approve**, **approve with changes**, or **reject** — this is the
   human-in-the-loop gate; the AI never assigns work on its own.
5. For an approved case, **Report outcome** with a before/after KPI value.
   An improvement resolves the case; a regression reopens it
   (`needs_reanalysis`) and bumps its priority so it resurfaces near the
   top of the backlog — the closed feedback loop.

## API reference

| Method | Path         | Purpose                                             |
|--------|--------------|------------------------------------------------------|
| POST   | `/seed`      | Load the bundled demo dataset                        |
| POST   | `/reset`     | Clear all in-memory data                              |
| POST   | `/ingest`    | Add feedback items and/or operational metrics         |
| POST   | `/analyze`   | Run the LangGraph pipeline over everything ingested   |
| GET    | `/issues`    | All issues ever created                               |
| GET    | `/issues/{id}` | A single issue                                     |
| GET    | `/backlog`   | Open issues, sorted by priority score                 |
| GET    | `/dashboard` | Summary stats for the top dashboard row                |
| POST   | `/validate`  | Approve / modify / reject an issue (human-in-the-loop) |
| POST   | `/outcomes`  | Report a before/after KPI value; resolves or reopens the case |
| GET    | `/outcomes`  | All recorded outcomes                                  |

## Project layout

```
backend/
  main.py           FastAPI app — the API gateway
  graph.py           LangGraph StateGraph wiring the pipeline
  store.py           In-memory store + issue taxonomy + deterministic scoring
  models.py           Pydantic request/response models
  sample_data.py      Bundled demo dataset for /seed
  requirements.txt

frontend/
  index.html          Loads React/Babel from CDN, mounts app.jsx
  app.jsx             The whole UI (dashboard, backlog, case detail, forms)
  styles.css           Visual design ("evidence board" console theme)

README.md
```

## Extending with a real LLM

`classify_feedback()` and `evaluate_hypotheses()` in `backend/store.py` are
the two functions standing in for the Issue Discovery / Root Cause agents'
semantic reasoning. Swap either for a call to your LLM of choice (OpenAI,
Anthropic, OpenRouter, etc.) — the LangGraph wiring in `graph.py` and every
downstream endpoint stay unchanged, since they only depend on the *shape*
of what those functions return, not how it's produced.

## Tests

```bash
cd backend
pip install -r requirements.txt -r requirements-dev.txt
pytest -q
```

The suite covers the health, seed, ingest, analyze, issue lookup and reset endpoints, plus JSON and CSV upload parsing.
