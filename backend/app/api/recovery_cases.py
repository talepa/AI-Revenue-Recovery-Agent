from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.models import AuditLog, Invoice, RecoveryAction, RecoveryCase
from app.schemas.recovery import AuditLogOut, RecoveryCaseDetailOut, RecoveryCaseListItemOut

router = APIRouter(prefix="/recovery-cases", tags=["recovery-cases"])


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
    case = result.scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")
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
