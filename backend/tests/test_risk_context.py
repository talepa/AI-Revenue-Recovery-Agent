import asyncio

import pytest
from sqlalchemy import select

from app.core.db import async_session_factory, engine
from app.models import Invoice
from app.seed.run import seed
from app.services.risk_context import build_risk_features

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest.fixture(scope="module", autouse=True)
def seeded_db():
    asyncio.run(seed())
    asyncio.run(engine.dispose())
    yield
    asyncio.run(engine.dispose())


async def _get_invoice(invoice_number: str) -> Invoice:
    async with async_session_factory() as session:
        result = await session.execute(select(Invoice).where(Invoice.invoice_number == invoice_number))
        invoice = result.scalar_one()
        return await build_risk_features(session, invoice)


async def test_risk_features_reflect_bluepeaks_repeated_late_payments():
    # Bluepeak's seeded history: paid 15, -2, 18, 15 days after due —
    # 3 late, 1 on-time, avg delay 11.5.
    features = await _get_invoice("INV-BLUEPEAK-2005")

    assert features.num_prior_late_payments == 3
    assert features.num_prior_on_time_payments == 1
    assert features.avg_historical_payment_delay == pytest.approx(11.5)
    assert features.days_overdue == 30
    assert features.outstanding_balance == pytest.approx(210_000.0)


async def test_risk_features_use_neutral_prior_for_customer_with_no_case_history():
    # None of the seeded companies have a prior CLOSED/CLOSED_UNRECOVERED
    # case yet (Aarav's case is CLOSED but it's the invoice under test
    # elsewhere) — Vertex specifically has zero prior recovery cases.
    features = await _get_invoice("INV-VERTEX-3010")

    assert features.prior_recovery_success_rate == 0.5
    assert features.days_overdue == 60
    assert features.outstanding_balance == pytest.approx(1_800_000.0)
