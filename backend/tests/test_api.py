"""API tests for the Evidence Board backend.

Run from the backend folder:  pytest -q
"""
import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app, parse_uploaded_file_data  # noqa: E402
from store import pct_change, priority_label  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_store():
    client.post("/reset")
    yield
    client.post("/reset")


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_seed_loads_demo_data():
    body = client.post("/seed").json()
    assert body["feedback_ingested"] > 0
    assert body["metrics_ingested"] > 0


def test_analyze_creates_ranked_issues():
    client.post("/seed")
    r = client.post("/analyze")
    assert r.status_code == 200

    issues = client.get("/issues").json()
    issues = issues.get("issues", issues) if isinstance(issues, dict) else issues
    assert len(issues) > 0


def test_unknown_issue_returns_404():
    assert client.get("/issues/does-not-exist").status_code == 404


def test_reset_clears_everything():
    client.post("/seed")
    client.post("/analyze")
    client.post("/reset")
    issues = client.get("/issues").json()
    issues = issues.get("issues", issues) if isinstance(issues, dict) else issues
    assert len(issues) == 0


def test_ingest_without_auto_analyze():
    payload = {
        "feedback": [{"channel": "app_review", "text": "App crashes every time I open checkout"}],
        "operational_metrics": [],
    }
    body = client.post("/ingest?auto_analyze=false", json=payload).json()
    assert body["feedback_ingested"] == 1
    assert body["auto_analyzed"] is False


def test_parse_json_upload():
    data = {
        "feedback": [{"text": "Refund took two weeks", "channel": "email"}],
        "operational_metrics": [{"name": "refund_days", "baseline": 5, "current": 14}],
    }
    fb, metrics = parse_uploaded_file_data("data.json", json.dumps(data).encode())
    assert len(fb) == 1 and fb[0]["text"] == "Refund took two weeks"
    assert metrics[0]["current"] == 14.0


def test_parse_csv_upload():
    csv_text = "text,channel\nDelivery was late again,survey\nLogin page keeps failing,support_ticket\n"
    fb, metrics = parse_uploaded_file_data("data.csv", csv_text.encode())
    assert len(fb) == 2
    assert fb[0]["text"] == "Delivery was late again"
    assert fb[1]["channel"] != "survey"  # channel column is read, not ignored
    assert metrics == []


def test_pct_change():
    assert pct_change(100, 150) == pytest.approx(0.5)


def test_priority_label_is_text():
    assert isinstance(priority_label(90), str)
