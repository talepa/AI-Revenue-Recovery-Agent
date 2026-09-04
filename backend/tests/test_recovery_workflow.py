import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.agents.graph import run_recovery_cycle
from app.core.db import async_session_factory, engine
from app.models import Company, Invoice, RecoveryAction, RecoveryCase
from app.models.enums import CompanySegment, InvoiceStatus, RecoveryCaseStatus
from app.seed.run import seed
from app.services.risk_engine import run_detection

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest.fixture(scope="module", autouse=True)
def seeded_db():
    asyncio.run(seed())
    asyncio.run(engine.dispose())
    yield
    asyncio.run(engine.dispose())


async def _create_overdue_case(
    name: str, invoice_number: str, amount: Decimal, days_overdue: int
) -> RecoveryCase:
    async with async_session_factory() as session:
        company = Company(name=name, industry="Testing", segment=CompanySegment.MID_MARKET)
        session.add(company)
        await session.flush()

        due = date.today() - timedelta(days=days_overdue)
        invoice = Invoice(
            company_id=company.id,
            invoice_number=invoice_number,
            amount_total=amount,
            amount_paid=Decimal("0.00"),
            issue_date=due - timedelta(days=30),
            due_date=due,
            status=InvoiceStatus.SENT,
        )
        session.add(invoice)
        await session.commit()

    async with async_session_factory() as session:
        result = await run_detection(session)

    case = next(c for c in result.cases_created if c.invoice_id == invoice.id)
    return case


async def test_first_cycle_sends_a_reminder_and_leaves_case_open():
    case = await _create_overdue_case(
        "Workflow Test Co A", "INV-WFTEST-A001", Decimal("150000.00"), days_overdue=5
    )

    async with async_session_factory() as session:
        final_state = await run_recovery_cycle(session, case.id)

    assert final_state["final_action"] == "SEND_EMAIL"
    assert final_state["policy_decision"] == "APPROVED"
    assert final_state["case_status"] == "OPEN"

    async with async_session_factory() as session:
        actions = (
            await session.execute(
                select(RecoveryAction).where(RecoveryAction.recovery_case_id == case.id)
            )
        ).scalars().all()
    assert len(actions) == 1
    assert actions[0].action_type.value == "SEND_EMAIL"
    assert actions[0].result is not None


async def test_high_value_overdue_case_gets_escalated_regardless_of_recommendation():
    # Matches the Vertex scenario's conditions: this forces policy to
    # override whatever the LLM/fallback recommends for a first cycle.
    case = await _create_overdue_case(
        "Workflow Test Co B", "INV-WFTEST-B001", Decimal("2000000.00"), days_overdue=50
    )

    async with async_session_factory() as session:
        final_state = await run_recovery_cycle(session, case.id)

    assert final_state["final_action"] == "ESCALATE"
    assert final_state["case_status"] == "ESCALATED"
    assert "forced" in final_state["policy_reason"].lower()

    async with async_session_factory() as session:
        refreshed = await session.get(RecoveryCase, case.id)
        assert refreshed.status == RecoveryCaseStatus.ESCALATED


async def test_payment_recovered_closes_the_case_on_next_cycle():
    case = await _create_overdue_case(
        "Workflow Test Co C", "INV-WFTEST-C001", Decimal("80000.00"), days_overdue=10
    )

    async with async_session_factory() as session:
        await run_recovery_cycle(session, case.id)  # first cycle: sends a reminder

    # Simulate the customer paying in full, outside the graph entirely.
    async with async_session_factory() as session:
        invoice = await session.get(Invoice, case.invoice_id)
        invoice.amount_paid = invoice.amount_total
        invoice.status = InvoiceStatus.PAID
        await session.commit()

    async with async_session_factory() as session:
        final_state = await run_recovery_cycle(session, case.id)

    assert final_state["case_status"] == "CLOSED"
    assert final_state["outcome_summary"] == "recovered"

    async with async_session_factory() as session:
        refreshed = await session.get(RecoveryCase, case.id)
        assert refreshed.status == RecoveryCaseStatus.CLOSED
        assert refreshed.recovered_amount == Decimal("80000.00")
        assert refreshed.closed_at is not None


async def test_running_a_terminal_case_is_a_no_op():
    # Aarav's seeded case is already CLOSED.
    async with async_session_factory() as session:
        invoice = (
            await session.execute(select(Invoice).where(Invoice.invoice_number == "INV-AARAV-1004"))
        ).scalar_one()
        case = (
            await session.execute(select(RecoveryCase).where(RecoveryCase.invoice_id == invoice.id))
        ).scalar_one()
        case_id = case.id

        actions_before = (
            await session.execute(select(RecoveryAction).where(RecoveryAction.recovery_case_id == case_id))
        ).scalars().all()

    async with async_session_factory() as session:
        final_state = await run_recovery_cycle(session, case_id)

    assert final_state.get("terminal") is True

    async with async_session_factory() as session:
        actions_after = (
            await session.execute(select(RecoveryAction).where(RecoveryAction.recovery_case_id == case_id))
        ).scalars().all()

    assert len(actions_after) == len(actions_before)
