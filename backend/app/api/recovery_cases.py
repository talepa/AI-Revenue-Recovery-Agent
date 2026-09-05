from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.graph import run_recovery_cycle
from app.core.config import settings
from app.core.db import get_db
from app.core.locks import LockAcquisitionError, acquire_lock
from app.models import AuditLog, Company, Invoice, RecoveryAction, RecoveryCase
from app.models.enums import AuditActor, ProposedBy, RecoveryActionStatus, RecoveryActionType
from app.schemas.recovery import (
    AuditLogOut,
    DetectionSummaryOut,
    RecoveryCaseDetailOut,
    RecoveryCaseListItemOut,
    SendReminderEmailOut,
)
from app.services.action_policy import evaluate_and_record_action, primary_contact
from app.services.risk_engine import run_detection
from app.tools.email_provider import send_reminder_email
from app.tools.mock_tools import execute_mock_action

router = APIRouter(prefix="/recovery-cases", tags=["recovery-cases"])


async def _load_case_detail(db: AsyncSession, case_id: UUID) -> RecoveryCase | None:
    stmt = (
        select(RecoveryCase)
        .where(RecoveryCase.id == case_id)
        .options(
            selectinload(RecoveryCase.invoice).selectinload(Invoice.company),
            selectinload(RecoveryCase.actions).selectinload(RecoveryAction.policy_decisions),
            selectinload(RecoveryCase.agent_decisions),
            selectinload(RecoveryCase.promises_to_pay),
            selectinload(RecoveryCase.communication_logs),
            selectinload(RecoveryCase.audit_logs),
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


@router.post("/detect-overdue", response_model=DetectionSummaryOut)
async def detect_overdue(db: AsyncSession = Depends(get_db)) -> DetectionSummaryOut:
    """Deterministic engine trigger: mark newly-overdue invoices, open cases for
    them, and resolve any promise-to-pay commitments whose date has passed.

    Also run automatically by the in-process scheduler when SCHEDULER_ENABLED
    is set. Returns 409 if a sweep is already in progress.
    """
    try:
        async with acquire_lock("detect-overdue"):
            result = await run_detection(db)
    except LockAcquisitionError:
        raise HTTPException(status_code=409, detail="A detection sweep is already in progress") from None
    return DetectionSummaryOut(
        invoices_marked_overdue=len(result.invoices_marked_overdue),
        cases_created=len(result.cases_created),
        case_ids=[c.id for c in result.cases_created],
        promises_fulfilled=len(result.promises_checked.fulfilled),
        promises_broken=len(result.promises_checked.broken),
    )


def _to_list_item(case: RecoveryCase) -> RecoveryCaseListItemOut:
    days_overdue = (date.today() - case.invoice.due_date).days
    current_action = case.actions[-1].action_type if case.actions else None
    return RecoveryCaseListItemOut(
        id=case.id,
        company_name=case.invoice.company.name,
        invoice_number=case.invoice.invoice_number,
        amount_total=case.invoice.amount_total,
        days_overdue=days_overdue,
        status=case.status,
        risk_level=case.risk_level,
        recovery_probability=case.recovery_probability,
        current_action=current_action,
        recovered_amount=case.recovered_amount,
    )


@router.get("", response_model=list[RecoveryCaseListItemOut])
async def list_recovery_cases(db: AsyncSession = Depends(get_db)) -> list[RecoveryCaseListItemOut]:
    stmt = (
        select(RecoveryCase)
        .options(
            selectinload(RecoveryCase.invoice).selectinload(Invoice.company),
            selectinload(RecoveryCase.actions),
        )
        .order_by(RecoveryCase.opened_at.desc())
    )
    result = await db.execute(stmt)
    cases = result.scalars().all()
    return [_to_list_item(c) for c in cases]


@router.get("/{case_id}", response_model=RecoveryCaseDetailOut)
async def get_recovery_case(case_id: UUID, db: AsyncSession = Depends(get_db)) -> RecoveryCase:
    case = await _load_case_detail(db, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")
    return case


@router.post("/{case_id}/run", response_model=RecoveryCaseDetailOut)
async def run_recovery_case(case_id: UUID, db: AsyncSession = Depends(get_db)) -> RecoveryCase:
    """Advance this case by exactly one recovery cycle through the LangGraph workflow.

    A no-op (case unchanged) if the case is already in a terminal state.
    Returns 409 if a cycle is already running for this case.
    """
    existing = await db.get(RecoveryCase, case_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")

    try:
        async with acquire_lock(f"recovery-case:{case_id}"):
            await run_recovery_cycle(db, case_id)
    except LockAcquisitionError:
        raise HTTPException(
            status_code=409, detail="A recovery cycle is already running for this case"
        ) from None

    case = await _load_case_detail(db, case_id)
    return case


@router.post("/{case_id}/send-reminder-email", response_model=SendReminderEmailOut)
async def send_reminder_email_endpoint(
    case_id: UUID, db: AsyncSession = Depends(get_db)
) -> SendReminderEmailOut:
    """Human-triggered real reminder email — always to settings.demo_notify_email,
    never a seeded contact's @example.com. Still goes through evaluate_policy()
    with the same reminder cap/cooldown rules as an automated cycle (proposed_by
    is HUMAN here, not AI, but the gate is identical).

    Errors clearly (400) if DEMO_NOTIFY_EMAIL isn't configured, rather than
    silently falling back to any other address. Returns 409 if a cycle/other
    action is already running for this case.
    """
    if not settings.demo_notify_email:
        raise HTTPException(
            status_code=400,
            detail=(
                "DEMO_NOTIFY_EMAIL is not configured. Set it in backend/.env and "
                "restart the API before sending a reminder."
            ),
        )

    case = await db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")

    try:
        async with acquire_lock(f"recovery-case:{case_id}"):
            invoice = await db.get(Invoice, case.invoice_id)
            company = await db.get(Company, case.company_id)
            contact = await primary_contact(db, case.company_id)

            recorded = await evaluate_and_record_action(
                db, case, invoice, RecoveryActionType.SEND_EMAIL, proposed_by=ProposedBy.HUMAN
            )
            action = recorded.action
            outcome = recorded.outcome
            now = datetime.now(timezone.utc)

            if outcome.final_action == RecoveryActionType.SEND_EMAIL:
                result = await send_reminder_email(db, case, invoice, contact, company.name)
                action.status = RecoveryActionStatus.EXECUTED
                action.executed_at = now
                action.result = result
                to = result["to"]
                status = result["status"]  # "SENT" or "SIMULATED"
                sent_at: datetime | None = now
                description = (
                    f"Real reminder email {'sent' if status == 'SENT' else 'simulated (no email provider configured)'} "
                    f"to {to}."
                )
            else:
                result = await execute_mock_action(db, outcome.final_action, case, invoice, contact)
                action.status = RecoveryActionStatus.EXECUTED
                action.executed_at = now
                action.result = result
                to = None
                status = "REJECTED"
                sent_at = None
                description = f"Policy substituted {outcome.final_action.value} instead of SEND_EMAIL: {outcome.reason}"

            await db.flush()
            db.add(
                AuditLog(
                    recovery_case_id=case.id,
                    entity_type="recovery_action",
                    entity_id=action.id,
                    event_type="EMAIL_SENT" if outcome.final_action == RecoveryActionType.SEND_EMAIL else "POLICY_SUBSTITUTED",
                    actor=AuditActor.SYSTEM,
                    description=description,
                    occurred_at=now,
                )
            )
            await db.commit()
    except LockAcquisitionError:
        raise HTTPException(
            status_code=409, detail="A recovery cycle is already running for this case"
        ) from None

    return SendReminderEmailOut(
        status=status,
        to=to,
        sent_at=sent_at,
        policy_decision=outcome.decision,
        reason=outcome.reason,
    )


@router.get("/{case_id}/audit-trail", response_model=list[AuditLogOut])
async def get_audit_trail(case_id: UUID, db: AsyncSession = Depends(get_db)) -> list[AuditLog]:
    case_exists = await db.execute(select(RecoveryCase.id).where(RecoveryCase.id == case_id))
    if case_exists.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")

    stmt = (
        select(AuditLog)
        .where(AuditLog.recovery_case_id == case_id)
        .order_by(AuditLog.occurred_at)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
