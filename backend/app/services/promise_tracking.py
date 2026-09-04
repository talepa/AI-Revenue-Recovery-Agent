"""Promise-to-pay follow-through: mark promises fulfilled or broken.

Runs as part of the same deterministic housekeeping sweep as overdue
detection (POST /recovery-cases/detect-overdue) — there's no separate
scheduler in V1 (see docs/architecture.md decision #2).
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Invoice, PromiseToPay
from app.models.enums import AuditActor, PromiseToPayStatus


@dataclass
class PromiseCheckResult:
    fulfilled: list[PromiseToPay]
    broken: list[PromiseToPay]


async def check_promises_to_pay(session: AsyncSession, *, today: date | None = None) -> PromiseCheckResult:
    today = today or date.today()
    now = datetime.now(timezone.utc)

    stmt = select(PromiseToPay).where(PromiseToPay.status == PromiseToPayStatus.PENDING)
    pending = list((await session.execute(stmt)).scalars().all())

    fulfilled: list[PromiseToPay] = []
    broken: list[PromiseToPay] = []

    for promise in pending:
        invoice = await session.get(Invoice, promise.invoice_id)

        if invoice.amount_paid >= invoice.amount_total:
            promise.status = PromiseToPayStatus.FULFILLED
            promise.fulfilled_at = now
            session.add(
                AuditLog(
                    recovery_case_id=promise.recovery_case_id,
                    entity_type="promise_to_pay",
                    entity_id=promise.id,
                    event_type="PROMISE_FULFILLED",
                    actor=AuditActor.SYSTEM,
                    description=(
                        f"Customer paid before/by the promised date "
                        f"({promise.promised_date.isoformat()}); promise fulfilled."
                    ),
                    occurred_at=now,
                )
            )
            fulfilled.append(promise)
        elif promise.promised_date < today:
            promise.status = PromiseToPayStatus.BROKEN
            session.add(
                AuditLog(
                    recovery_case_id=promise.recovery_case_id,
                    entity_type="promise_to_pay",
                    entity_id=promise.id,
                    event_type="PROMISE_BROKEN",
                    actor=AuditActor.SYSTEM,
                    description=(
                        f"Promised payment of ₹{promise.promised_amount:,.2f} by "
                        f"{promise.promised_date.isoformat()} was not received; promise broken."
                    ),
                    occurred_at=now,
                )
            )
            broken.append(promise)

    await session.flush()
    return PromiseCheckResult(fulfilled=fulfilled, broken=broken)


async def has_unresolved_broken_promise(session: AsyncSession, case_id) -> bool:
    stmt = select(PromiseToPay.id).where(
        PromiseToPay.recovery_case_id == case_id,
        PromiseToPay.status == PromiseToPayStatus.BROKEN,
    )
    return (await session.execute(stmt)).first() is not None
