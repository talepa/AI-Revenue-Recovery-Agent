"""Structured LLM outputs.

These are the hard guarantee behind "the LLM must not invent arbitrary
actions": InterventionRecommendation.action is a closed Literal, so
Pydantic validation rejects anything outside the fixed action set,
regardless of what a model tries to return.
"""

from typing import Literal

from pydantic import BaseModel, Field


class DiagnosisResult(BaseModel):
    diagnosis: str = Field(description="One-sentence description of the likely situation")
    reason: str = Field(description="Brief supporting rationale, 1-2 sentences")
    recommended_priority: Literal["low", "medium", "high"]


class InterventionRecommendation(BaseModel):
    action: Literal[
        "SEND_EMAIL",
        "SEND_PAYMENT_LINK",
        "TRACK_PROMISE_TO_PAY",
        "ESCALATE",
        "WAIT",
        "CLOSE_CASE",
    ]
    rationale: str = Field(description="Brief explanation for why this action, 1-2 sentences")
