"""
Pydantic models shared across the API.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, ConfigDict


Channel = Literal["app_review", "support_ticket", "survey", "email", "social"]

def normalize_channel(val: Optional[str]) -> str:
    if not val:
        return "survey"
    v = str(val).strip().lower()
    if v in ("app_review", "app review", "app_store", "play_store", "store", "review", "reviews"):
        return "app_review"
    if v in ("support_ticket", "support", "ticket", "zendesk", "intercom", "chat", "helpdesk", "case"):
        return "support_ticket"
    if v in ("email", "mail", "inbox"):
        return "email"
    if v in ("social", "twitter", "x", "reddit", "facebook", "linkedin", "social_media"):
        return "social"
    if v in ("survey", "nps", "csat", "feedback_form", "web", "form"):
        return "survey"
    return "survey"


class FeedbackItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: Optional[str] = None
    channel: str = "survey"
    text: str
    customer_id: Optional[str] = None
    category: Optional[str] = None
    timestamp: Optional[str] = None

    def model_post_init(self, __context) -> None:
        self.channel = normalize_channel(self.channel)


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

class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
