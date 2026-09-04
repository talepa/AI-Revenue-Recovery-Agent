"""Deterministic revenue-at-risk detection and recovery-case creation.

Detecting overdue invoices and opening a case is a bookkeeping decision, not
a judgment call, so it stays deterministic — this is the "Event -> Revenue
Risk Assessment -> Recovery Case" stage from the architecture. Once a case
exists, it's immediately scored by the XGBoost model (app/ml/risk_model.py,
trained on synthetic data — see that module for the "not a production
financial model" caveat) — that's the "Context Gathering -> Risk/Probability
Model" stage. AI diagnosis/recommendation (Phase 8/9) still attach later.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ml.risk_model import score as score_risk
from app.models import AuditLog, Invoice, PaymentEvent, RecoveryCase
from app.models.enums import AuditActor, InvoiceStatus, PaymentEventType, RecoveryCaseStatus
from app.services.risk_context import build_risk_features

# TODO(Phase 10): move into the formal deterministic policy engine config,
# alongside MAX_EMAIL_REMINDERS, HIGH_VALUE_THRESHOLD, etc.
MAX_RECOVERY_DAYS = 90


@dataclass
class DetectionResult:
    invoices_marked_overdue: list[Invoice]
    cases_created: list[RecoveryCase]


async def mark_overdue_invoices(session: AsyncSession, *, today: date | None = None) -> list[Invoice]:
    """Flip SENT/PARTIALLY_PAID invoices whose due date has passed to OVERDUE."""
    today = today or date.today()
    stmt = select(Invoice).where(
        Invoice.due_date < today,
        Invoice.status.in_([InvoiceStatus.SENT, InvoiceStatus.PARTIALLY_PAID]),
    )
    result = await session.execute(stmt)
    invoices = list(result.scalars().all())

    now = datetime.now(timezone.utc)
    for invoice in invoices:
        invoice.status = InvoiceStatus.OVERDUE
        session.add(
            PaymentEvent(
                invoice_id=invoice.id,
                event_type=PaymentEventType.INVOICE_OVERDUE,
                payload={"due_date": invoice.due_date.isoformat()},
                occurred_at=now,
            )
        )
    await session.flush()
    return invoices


async def create_recovery_cases_for_overdue_invoices(session: AsyncSession) -> list[RecoveryCase]:
    """Create a recovery case for every OVERDUE invoice that doesn't already have one."""
    stmt = (
        select(Invoice)
        .outerjoin(RecoveryCase, RecoveryCase.invoice_id == Invoice.id)
        .where(Invoice.status == InvoiceStatus.OVERDUE, RecoveryCase.id.is_(None))
    )
    result = await session.execute(stmt)
    invoices = list(result.scalars().all())

    now = datetime.now(timezone.utc)
    created: list[RecoveryCase] = []
    for invoice in invoices:
        revenue_at_risk = invoice.amount_total - invoice.amount_paid
        case = RecoveryCase(
            invoice_id=invoice.id,
            company_id=invoice.company_id,
            status=RecoveryCaseStatus.OPEN,
            opened_at=now,
            revenue_at_risk=revenue_at_risk,
            recovery_window_deadline=invoice.due_date + timedelta(days=MAX_RECOVERY_DAYS),
        )
        session.add(case)
        await session.flush()

        session.add(
            AuditLog(
                recovery_case_id=case.id,
                entity_type="recovery_case",
                entity_id=case.id,
                event_type="CASE_CREATED",
                actor=AuditActor.SYSTEM,
                description=(
                    f"Recovery case opened for overdue invoice {invoice.invoice_number} "
                    f"(₹{revenue_at_risk:,.2f} at risk)."
                ),
                occurred_at=now,
            )
        )

        features = await build_risk_features(session, invoice)
        risk_result = score_risk(features)
        case.risk_score = Decimal(str(risk_result.risk_score))
        case.risk_level = risk_result.risk_level
        case.recovery_probability = Decimal(str(risk_result.recovery_probability))

        session.add(
            AuditLog(
                recovery_case_id=case.id,
                entity_type="recovery_case",
                entity_id=case.id,
                event_type="RISK_SCORED",
                actor=AuditActor.SYSTEM,
                description=(
                    f"Risk scored via ML model (synthetic training data): "
                    f"{risk_result.risk_level.value} ({risk_result.risk_score}), "
                    f"recovery probability {risk_result.recovery_probability:.0%}."
                ),
                occurred_at=now,
            )
        )

        created.append(case)

    await session.flush()
    return created


async def run_detection(session: AsyncSession, *, today: date | None = None) -> DetectionResult:
    """Run the full detection pass: mark overdue invoices, then open cases for them."""
    invoices_marked = await mark_overdue_invoices(session, today=today)
    cases_created = await create_recovery_cases_for_overdue_invoices(session)
    await session.commit()
    return DetectionResult(invoices_marked_overdue=invoices_marked, cases_created=cases_created)
