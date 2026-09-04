from app.models.enums import PolicyDecisionResult, RecoveryActionType, RecoveryCaseStatus
from app.services.policy_engine import (
    ESCALATION_DAYS_THRESHOLD,
    HIGH_VALUE_THRESHOLD,
    MAX_EMAIL_REMINDERS,
    MIN_TIME_BETWEEN_REMINDERS_DAYS,
    evaluate_policy,
)


def test_first_reminder_is_approved():
    outcome = evaluate_policy(
        recommended_action=RecoveryActionType.SEND_EMAIL,
        reminder_count=0,
        days_overdue=5,
        revenue_at_risk=100_000.0,
        case_status=RecoveryCaseStatus.OPEN,
        days_since_last_action=None,
    )
    assert outcome.final_action == RecoveryActionType.SEND_EMAIL
    assert outcome.decision == PolicyDecisionResult.APPROVED


def test_reminder_cap_forces_escalation():
    outcome = evaluate_policy(
        recommended_action=RecoveryActionType.SEND_EMAIL,
        reminder_count=MAX_EMAIL_REMINDERS,
        days_overdue=30,
        revenue_at_risk=100_000.0,
        case_status=RecoveryCaseStatus.OPEN,
        days_since_last_action=10,
    )
    assert outcome.final_action == RecoveryActionType.ESCALATE
    assert outcome.decision == PolicyDecisionResult.REJECTED


def test_cooldown_not_elapsed_forces_wait():
    outcome = evaluate_policy(
        recommended_action=RecoveryActionType.SEND_EMAIL,
        reminder_count=1,
        days_overdue=10,
        revenue_at_risk=100_000.0,
        case_status=RecoveryCaseStatus.OPEN,
        days_since_last_action=MIN_TIME_BETWEEN_REMINDERS_DAYS - 1,
    )
    assert outcome.final_action == RecoveryActionType.WAIT
    assert outcome.decision == PolicyDecisionResult.REJECTED


def test_high_value_reminder_approved_but_flagged_for_review():
    outcome = evaluate_policy(
        recommended_action=RecoveryActionType.SEND_PAYMENT_LINK,
        reminder_count=1,
        days_overdue=20,
        revenue_at_risk=HIGH_VALUE_THRESHOLD + 1,
        case_status=RecoveryCaseStatus.OPEN,
        days_since_last_action=MIN_TIME_BETWEEN_REMINDERS_DAYS,
    )
    assert outcome.final_action == RecoveryActionType.SEND_PAYMENT_LINK
    assert outcome.decision == PolicyDecisionResult.REQUIRES_HUMAN_REVIEW


def test_high_value_and_overdue_forces_escalation_even_on_first_cycle():
    # This is the Vertex scenario from the seed data: even a fresh
    # recommendation of SEND_EMAIL gets overridden the moment the case is
    # both high-value and past the escalation threshold.
    outcome = evaluate_policy(
        recommended_action=RecoveryActionType.SEND_EMAIL,
        reminder_count=0,
        days_overdue=ESCALATION_DAYS_THRESHOLD,
        revenue_at_risk=HIGH_VALUE_THRESHOLD,
        case_status=RecoveryCaseStatus.OPEN,
        days_since_last_action=None,
    )
    assert outcome.final_action == RecoveryActionType.ESCALATE
    assert outcome.decision == PolicyDecisionResult.APPROVED
    assert "forced" in outcome.reason.lower()


def test_broken_promise_forces_escalation_regardless_of_recommendation():
    outcome = evaluate_policy(
        recommended_action=RecoveryActionType.WAIT,
        reminder_count=1,
        days_overdue=15,
        revenue_at_risk=100_000.0,
        case_status=RecoveryCaseStatus.MONITORING,
        days_since_last_action=3,
        has_broken_promise=True,
    )
    assert outcome.final_action == RecoveryActionType.ESCALATE
    assert outcome.decision == PolicyDecisionResult.APPROVED
    assert "promise" in outcome.reason.lower()


def test_escalated_case_suppresses_further_reminders():
    outcome = evaluate_policy(
        recommended_action=RecoveryActionType.SEND_EMAIL,
        reminder_count=1,
        days_overdue=50,
        revenue_at_risk=100_000.0,
        case_status=RecoveryCaseStatus.ESCALATED,
        days_since_last_action=20,
    )
    assert outcome.final_action == RecoveryActionType.WAIT
    assert outcome.decision == PolicyDecisionResult.REJECTED


def test_promise_to_pay_and_wait_are_never_gated():
    # Deliberately below both HIGH_VALUE_THRESHOLD and ESCALATION_DAYS_THRESHOLD,
    # so the forced-escalation rule doesn't kick in and mask what this test checks.
    for action in (RecoveryActionType.TRACK_PROMISE_TO_PAY, RecoveryActionType.WAIT, RecoveryActionType.CLOSE_CASE):
        outcome = evaluate_policy(
            recommended_action=action,
            reminder_count=5,
            days_overdue=20,
            revenue_at_risk=100_000.0,
            case_status=RecoveryCaseStatus.OPEN,
            days_since_last_action=0,
        )
        assert outcome.final_action == action
        assert outcome.decision == PolicyDecisionResult.APPROVED
