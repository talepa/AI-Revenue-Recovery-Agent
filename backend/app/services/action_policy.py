"""Shared "evaluate_policy → record RecoveryAction/PolicyDecision/AuditLog"
step, for the new human-triggered entry points (real reminder email, voice
call) that aren't a full LangGraph cycle but still must never bypass the
policy engine.

This intentionally duplicates three small query helpers that also exist
(as module-private functions) in app/agents/graph.py, rather than importing
or modifying that module — graph.py's nodes are tested and working exactly
as they are, and this is new, separate call sites, not a refactor of the
existing workflow.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Contact, Invoice, PolicyDecision, RecoveryAction, RecoveryCase
from app.models.enums import (
    AuditActor,
    ProposedBy,
    RecoveryActionStatus,
    RecoveryActionType,
)
from app.services.policy_engine import PolicyOutcome, evaluate_policy
from app.services.promise_tracking import has_unresolved_broken_promise


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _reminder_count(session: AsyncSession, case_id: UUID) -> int:
    stmt = select(func.count(RecoveryAction.id)).where(
        RecoveryAction.recovery_case_id == case_id,
        RecoveryAction.action_type.in_([RecoveryActionType.SEND_EMAIL, RecoveryActionType.SEND_PAYMENT_LINK]),
        RecoveryAction.status == RecoveryActionStatus.EXECUTED,
    )
    return (await session.execute(stmt)).scalar_one()


async def _last_action_at(session: AsyncSession, case_id: UUID) -> datetime | None:
    stmt = (
        select(RecoveryAction.executed_at)
        .where(RecoveryAction.recovery_case_id == case_id, RecoveryAction.status == RecoveryActionStatus.EXECUTED)
        .order_by(RecoveryAction.executed_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _next_sequence_number(session: AsyncSession, case_id: UUID) -> int:
    stmt = select(func.coalesce(func.max(RecoveryAction.sequence_number), 0)).where(
        RecoveryAction.recovery_case_id == case_id
    )
    return (await session.execute(stmt)).scalar_one() + 1


async def primary_contact(session: AsyncSession, company_id: UUID) -> Contact | None:
    stmt = (
        select(Contact)
        .where(Contact.company_id == company_id)
        .order_by(Contact.is_primary.desc(), Contact.created_at)
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


@dataclass
class RecordedAction:
    action: RecoveryAction
    outcome: PolicyOutcome


async def evaluate_and_record_action(
    session: AsyncSession,
    case: RecoveryCase,
    invoice: Invoice,
    recommended_action: RecoveryActionType,
    *,
    proposed_by: ProposedBy,
) -> RecordedAction:
    """Run recommended_action through evaluate_policy() and persist exactly
    the same RecoveryAction/PolicyDecision/AuditLog shape policy_check_node
    writes for a graph cycle — so a human-triggered email or voice action is
    just as fully audited as an automated one. Does NOT execute any tool;
    callers decide what to do with outcome.final_action (see
    app/tools/mock_tools.execute_mock_action / app/tools/email_provider.send_reminder_email).
    """
    days_overdue = max((date.today() - invoice.due_date).days, 0)
    reminder_count = await _reminder_count(session, case.id)
    last_action_at = await _last_action_at(session, case.id)
    days_since_last_action = (date.today() - last_action_at.date()).days if last_action_at else None
    has_broken_promise = await has_unresolved_broken_promise(session, case.id)

    outcome = evaluate_policy(
        recommended_action=recommended_action,
        reminder_count=reminder_count,
        days_overdue=days_overdue,
        revenue_at_risk=float(case.revenue_at_risk),
        case_status=case.status,
        days_since_last_action=days_since_last_action,
        has_broken_promise=has_broken_promise,
    )

    seq = await _next_sequence_number(session, case.id)
    action = RecoveryAction(
        recovery_case_id=case.id,
        action_type=outcome.final_action,
        recommended_action_type=recommended_action,
        status=RecoveryActionStatus.PROPOSED,
        proposed_by=proposed_by,
        sequence_number=seq,
    )
    session.add(action)
    await session.flush()

    action.status = (
        RecoveryActionStatus.POLICY_REJECTED
        if outcome.decision.value == "REJECTED"
        else RecoveryActionStatus.POLICY_APPROVED
    )

    session.add(
        PolicyDecision(
            recovery_action_id=action.id,
            policy_name="deterministic_policy_engine",
            decision=outcome.decision,
            reason=outcome.reason,
            rule=outcome.rule,
            evaluated_at=_now(),
        )
    )
    session.add(
        AuditLog(
            recovery_case_id=case.id,
            entity_type="recovery_action",
            entity_id=action.id,
            event_type=f"POLICY_{outcome.decision.value}",
            actor=AuditActor.POLICY_ENGINE,
            description=outcome.reason,
            occurred_at=_now(),
        )
    )
    await session.flush()

    return RecordedAction(action=action, outcome=outcome)
