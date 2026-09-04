from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.graph import run_recovery_cycle
from app.core.db import get_db
from app.models import AuditLog, Invoice, RecoveryAction, RecoveryCase
from app.schemas.recovery import (
    AuditLogOut,
    DetectionSummaryOut,
    RecoveryCaseDetailOut,
    RecoveryCaseListItemOut,
)
from app.services.risk_engine import run_detection

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

    Manually/cron-triggered for V1 — no long-running consumer (see docs/architecture.md).
    """
    result = await run_detection(db)
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
    """
    existing = await db.get(RecoveryCase, case_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")

    await run_recovery_cycle(db, case_id)

    case = await _load_case_detail(db, case_id)
    return case


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
