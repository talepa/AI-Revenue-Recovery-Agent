from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.models import Invoice, Payment, PaymentEvent
from app.models.enums import InvoiceStatus, PaymentEventType, PaymentMethod, PaymentStatus
from app.schemas.invoice import InvoiceOut, SimulatePaymentIn

router = APIRouter(prefix="/invoices", tags=["invoices"])


@router.get("", response_model=list[InvoiceOut])
async def list_invoices(
    status_filter: InvoiceStatus | None = Query(None, alias="status"),
    company_id: UUID | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> list[Invoice]:
    stmt = select(Invoice).options(selectinload(Invoice.company)).order_by(Invoice.due_date.desc())
    if status_filter is not None:
        stmt = stmt.where(Invoice.status == status_filter)
    if company_id is not None:
        stmt = stmt.where(Invoice.company_id == company_id)
    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


# Must come before /{invoice_id} — otherwise "overdue" is parsed as a UUID and 422s.
@router.get("/overdue", response_model=list[InvoiceOut])
async def list_overdue_invoices(db: AsyncSession = Depends(get_db)) -> list[Invoice]:
    stmt = (
        select(Invoice)
        .options(selectinload(Invoice.company))
        .where(Invoice.status == InvoiceStatus.OVERDUE)
        .order_by(Invoice.due_date)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{invoice_id}", response_model=InvoiceOut)
async def get_invoice(invoice_id: UUID, db: AsyncSession = Depends(get_db)) -> Invoice:
    stmt = select(Invoice).options(selectinload(Invoice.company)).where(Invoice.id == invoice_id)
    result = await db.execute(stmt)
    invoice = result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


@router.post("/{invoice_id}/simulate-payment", response_model=InvoiceOut)
async def simulate_payment(
    invoice_id: UUID, payload: SimulatePaymentIn | None = None, db: AsyncSession = Depends(get_db)
) -> Invoice:
    """Mock payment simulation — stands in for a real payment gateway webhook.

    Lets the demo close the loop on "customer actually pays": records a
    Payment, updates the invoice, and lets the next `/recovery-cases/{id}/run`
    call detect it and close the case.
    """
    invoice = await db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    outstanding: Decimal = invoice.amount_total - invoice.amount_paid
    if outstanding <= 0:
        raise HTTPException(status_code=400, detail="Invoice has no outstanding balance")

    amount = payload.amount if payload and payload.amount is not None else outstanding
    amount = min(amount, outstanding)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Payment amount must be positive")

    now = datetime.now(timezone.utc)
    db.add(
        Payment(
            invoice_id=invoice.id,
            amount=amount,
            payment_date=now,
            method=PaymentMethod.BANK_TRANSFER,
            status=PaymentStatus.SUCCESS,
        )
    )
    invoice.amount_paid += amount
    invoice.status = (
        InvoiceStatus.PAID if invoice.amount_paid >= invoice.amount_total else InvoiceStatus.PARTIALLY_PAID
    )
    db.add(
        PaymentEvent(
            invoice_id=invoice.id,
            event_type=PaymentEventType.PAYMENT_RECEIVED,
            payload={"amount": str(amount), "simulated": True},
            occurred_at=now,
        )
    )
    await db.commit()

    stmt = select(Invoice).options(selectinload(Invoice.company)).where(Invoice.id == invoice_id)
    result = await db.execute(stmt)
    return result.scalar_one()
