from decimal import Decimal

from pydantic import BaseModel


class DashboardMetricsOut(BaseModel):
    total_revenue_at_risk: Decimal
    total_revenue_recovered: Decimal
    recovery_rate: float | None
    active_cases: int
    escalated_cases: int
    average_days_overdue: float | None
    cases_by_risk_level: dict[str, int]
