"""Aggregate revenue-recovery metrics for the dashboard.

All numbers come from real aggregate queries over recovery_cases/invoices —
nothing here is precomputed or cached at write time, since the dataset is
small enough that recomputing on read is simpler and can't drift.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Invoice, RecoveryCase
from app.models.enums import RecoveryCaseStatus

ACTIVE_STATUSES = [RecoveryCaseStatus.OPEN, RecoveryCaseStatus.MONITORING, RecoveryCaseStatus.ESCALATED]


@dataclass
class DashboardMetrics:
    total_revenue_at_risk: Decimal
    total_revenue_recovered: Decimal
    recovery_rate: float | None
    active_cases: int
    escalated_cases: int
    average_days_overdue: float | None
    cases_by_risk_level: dict[str, int]


async def get_dashboard_metrics(session: AsyncSession) -> DashboardMetrics:
    total_at_risk_result = await session.execute(
        select(func.coalesce(func.sum(RecoveryCase.revenue_at_risk), 0)).where(
            RecoveryCase.status.in_(ACTIVE_STATUSES)
        )
    )
    total_revenue_at_risk = total_at_risk_result.scalar_one()

    total_recovered_result = await session.execute(
        select(func.coalesce(func.sum(RecoveryCase.recovered_amount), 0))
    )
    total_revenue_recovered = total_recovered_result.scalar_one()

    # Of the revenue that has ever been at risk (currently at risk + already
    # recovered), what fraction has actually been recovered so far.
    denominator = total_revenue_at_risk + total_revenue_recovered
    recovery_rate = float(total_revenue_recovered / denominator) if denominator else None

    active_cases_result = await session.execute(
        select(func.count(RecoveryCase.id)).where(RecoveryCase.status.in_(ACTIVE_STATUSES))
    )
    active_cases = active_cases_result.scalar_one()

    escalated_cases_result = await session.execute(
        select(func.count(RecoveryCase.id)).where(RecoveryCase.status == RecoveryCaseStatus.ESCALATED)
    )
    escalated_cases = escalated_cases_result.scalar_one()

    avg_days_result = await session.execute(
        select(func.avg(func.current_date() - Invoice.due_date))
        .join(RecoveryCase, RecoveryCase.invoice_id == Invoice.id)
        .where(RecoveryCase.status.in_(ACTIVE_STATUSES))
    )
    avg_days_raw = avg_days_result.scalar_one()
    average_days_overdue = float(avg_days_raw) if avg_days_raw is not None else None

    risk_level_result = await session.execute(
        select(RecoveryCase.risk_level, func.count(RecoveryCase.id)).group_by(RecoveryCase.risk_level)
    )
    cases_by_risk_level = {
        (level.value if level else "UNSCORED"): count for level, count in risk_level_result.all()
    }

    return DashboardMetrics(
        total_revenue_at_risk=total_revenue_at_risk,
        total_revenue_recovered=total_revenue_recovered,
        recovery_rate=recovery_rate,
        active_cases=active_cases,
        escalated_cases=escalated_cases,
        average_days_overdue=average_days_overdue,
        cases_by_risk_level=cases_by_risk_level,
    )
