from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.companies import router as companies_router
from app.api.dashboard import router as dashboard_router
from app.api.health import router as health_router
from app.api.invoices import router as invoices_router
from app.api.recovery_cases import router as recovery_cases_router
from app.core.config import settings
from app.events import get_publisher


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await get_publisher().close()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.include_router(health_router)
app.include_router(companies_router)
app.include_router(invoices_router)
app.include_router(recovery_cases_router)
app.include_router(dashboard_router)
