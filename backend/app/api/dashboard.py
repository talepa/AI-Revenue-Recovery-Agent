from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.schemas.dashboard import DashboardMetricsOut
from app.services.metrics import get_dashboard_metrics

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/metrics", response_model=DashboardMetricsOut)
async def dashboard_metrics(db: AsyncSession = Depends(get_db)) -> DashboardMetricsOut:
    metrics = await get_dashboard_metrics(db)
    return DashboardMetricsOut(**metrics.__dict__)
