"""Deterministic policy engine — the only layer allowed to gate execution.

The LLM (app/agents/) recommends an action; this module decides whether it
actually happens, and can override it outright. Every decision is
auditable (PolicyDecision rows) and nothing here depends on prompting a
model to "be careful" — it's plain Python against configured thresholds.

TODO(Phase 10): make these thresholds configurable (env/DB) instead of
module constants, and add per-segment overrides.
"""

from dataclasses import dataclass

from app.models.enums import PolicyDecisionResult, RecoveryActionType, RecoveryCaseStatus

MAX_EMAIL_REMINDERS = 3
MIN_TIME_BETWEEN_REMINDERS_DAYS = 7
HIGH_VALUE_THRESHOLD = 1_000_000.0
ESCALATION_DAYS_THRESHOLD = 45

_REMINDER_ACTIONS = (RecoveryActionType.SEND_EMAIL, RecoveryActionType.SEND_PAYMENT_LINK)


@dataclass
class PolicyOutcome:
    final_action: RecoveryActionType
    decision: PolicyDecisionResult
    reason: str


def evaluate_policy(
    *,
    recommended_action: RecoveryActionType,
    reminder_count: int,
    days_overdue: int,
    revenue_at_risk: float,
    case_status: RecoveryCaseStatus,
    days_since_last_action: int | None,
) -> PolicyOutcome:
    # Forced escalation: high value + significantly overdue overrides everything,
    # including a recommendation to WAIT or send another reminder.
    if revenue_at_risk >= HIGH_VALUE_THRESHOLD and days_overdue >= ESCALATION_DAYS_THRESHOLD:
        return PolicyOutcome(
            final_action=RecoveryActionType.ESCALATE,
            decision=PolicyDecisionResult.APPROVED,
            reason=(
                f"Amount (₹{revenue_at_risk:,.2f}) exceeds HIGH_VALUE_THRESHOLD "
                f"(₹{HIGH_VALUE_THRESHOLD:,.2f}) and days overdue ({days_overdue}) exceeds "
                f"ESCALATION_THRESHOLD ({ESCALATION_DAYS_THRESHOLD}); escalation forced "
                f"regardless of AI recommendation."
            ),
        )

    # Once escalated, a human has taken over — automated reminders stop.
    if case_status == RecoveryCaseStatus.ESCALATED and recommended_action in _REMINDER_ACTIONS:
        return PolicyOutcome(
            final_action=RecoveryActionType.WAIT,
            decision=PolicyDecisionResult.REJECTED,
            reason="Case is already escalated to a human; automated reminders are suppressed.",
        )

    if recommended_action in _REMINDER_ACTIONS:
        if reminder_count >= MAX_EMAIL_REMINDERS:
            return PolicyOutcome(
                final_action=RecoveryActionType.ESCALATE,
                decision=PolicyDecisionResult.REJECTED,
                reason=(
                    f"Reminder count ({reminder_count}) has reached MAX_EMAIL_REMINDERS "
                    f"({MAX_EMAIL_REMINDERS}); escalating instead."
                ),
            )
        if days_since_last_action is not None and days_since_last_action < MIN_TIME_BETWEEN_REMINDERS_DAYS:
            return PolicyOutcome(
                final_action=RecoveryActionType.WAIT,
                decision=PolicyDecisionResult.REJECTED,
                reason=(
                    f"Only {days_since_last_action} day(s) since the last reminder; "
                    f"MIN_TIME_BETWEEN_REMINDERS_DAYS ({MIN_TIME_BETWEEN_REMINDERS_DAYS}) not yet elapsed."
                ),
            )
        if revenue_at_risk >= HIGH_VALUE_THRESHOLD:
            return PolicyOutcome(
                final_action=recommended_action,
                decision=PolicyDecisionResult.REQUIRES_HUMAN_REVIEW,
                reason=(
                    f"Amount (₹{revenue_at_risk:,.2f}) exceeds HIGH_VALUE_THRESHOLD; "
                    f"action approved but flagged for human review."
                ),
            )
        return PolicyOutcome(
            final_action=recommended_action,
            decision=PolicyDecisionResult.APPROVED,
            reason=f"Reminder count ({reminder_count}) below MAX_EMAIL_REMINDERS ({MAX_EMAIL_REMINDERS}).",
        )

    # TRACK_PROMISE_TO_PAY, ESCALATE, WAIT, CLOSE_CASE: no additional gating in V1.
    return PolicyOutcome(
        final_action=recommended_action,
        decision=PolicyDecisionResult.APPROVED,
        reason=f"No policy restriction applies to {recommended_action.value}.",
    )
