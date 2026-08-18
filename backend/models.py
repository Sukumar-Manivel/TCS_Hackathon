"""
Pydantic models shared across the API.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


Channel = Literal["app_review", "support_ticket", "survey", "email", "social"]


class FeedbackItem(BaseModel):
    id: Optional[str] = None
    channel: Channel
    text: str
    customer_id: Optional[str] = None
    timestamp: Optional[str] = None


class OperationalMetric(BaseModel):
    name: str
    baseline: float
    current: float
    unit: Optional[str] = ""


class IngestPayload(BaseModel):
    feedback: List[FeedbackItem] = Field(default_factory=list)
    operational_metrics: List[OperationalMetric] = Field(default_factory=list)


class ValidationDecision(BaseModel):
    issue_id: str
    decision: Literal["approved", "modified", "rejected"]
    owner: Optional[str] = None
    notes: Optional[str] = None
    modified_action: Optional[str] = None


class OutcomeReport(BaseModel):
    issue_id: str
    kpi_name: str
    before_value: float
    after_value: float
    target_value: Optional[float] = None
    reported_at: Optional[str] = None
