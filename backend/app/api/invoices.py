from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.models import Invoice
from app.models.enums import InvoiceStatus
from app.schemas.invoice import InvoiceOut

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
