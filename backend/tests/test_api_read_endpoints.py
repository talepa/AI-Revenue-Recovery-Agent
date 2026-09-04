import asyncio
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.db import engine
from app.main import app
from app.seed.run import seed

NIL_UUID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture(scope="module")
def client():
    asyncio.run(seed())
    # The engine's pooled connections are bound to the event loop that just
    # closed with asyncio.run(); dispose so the TestClient's requests (on
    # its own portal loop) open fresh connections instead of reusing dead ones.
    asyncio.run(engine.dispose())

    # Used as a context manager so all requests share one background event
    # loop (a "portal") for the lifetime of the fixture — without this,
    # every individual .get() call gets its own loop, which the async
    # SQLAlchemy engine's connection pool can't survive across calls.
    with TestClient(app) as test_client:
        yield test_client

    # Likewise, dispose after this module's portal loop closes, so later
    # test modules (their own event loop) don't inherit dead connections.
    asyncio.run(engine.dispose())


def test_list_companies(client):
    resp = client.get("/companies")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 6
    assert {c["name"] for c in data} >= {"Vertex Infra Solutions", "Northwind Traders Pvt Ltd"}


def test_get_company_detail_includes_contacts(client):
    company_id = client.get("/companies").json()[0]["id"]
    resp = client.get(f"/companies/{company_id}")
    assert resp.status_code == 200
    assert len(resp.json()["contacts"]) >= 1


def test_get_company_404(client):
    resp = client.get(f"/companies/{NIL_UUID}")
    assert resp.status_code == 404


def test_list_overdue_invoices(client):
    resp = client.get("/invoices/overdue")
    assert resp.status_code == 200
    data = resp.json()
    numbers = {inv["invoice_number"] for inv in data}
    assert numbers == {
        "INV-NORTHWIND-2001",
        "INV-BLUEPEAK-2005",
        "INV-VERTEX-3010",
        "INV-SUNDIAL-4002",
    }
    for inv in data:
        assert inv["status"] == "OVERDUE"
        assert inv["amount_total"] != inv["amount_paid"]


def test_invoice_overdue_route_not_shadowed_by_id_route(client):
    # /invoices/overdue must resolve to the overdue-list route, not a 422
    # from trying to parse "overdue" as a UUID path param.
    resp = client.get("/invoices/overdue")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_invoice_404(client):
    resp = client.get(f"/invoices/{NIL_UUID}")
    assert resp.status_code == 404


def test_list_recovery_cases_matches_dashboard_shape(client):
    resp = client.get("/recovery-cases")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 5

    by_invoice = {c["invoice_number"]: c for c in data}
    assert by_invoice["INV-VERTEX-3010"]["status"] == "ESCALATED"
    assert by_invoice["INV-VERTEX-3010"]["risk_level"] == "HIGH"
    assert by_invoice["INV-VERTEX-3010"]["current_action"] == "ESCALATE"
    assert by_invoice["INV-VERTEX-3010"]["days_overdue"] == 60

    assert by_invoice["INV-AARAV-1004"]["status"] == "CLOSED"
    assert by_invoice["INV-AARAV-1004"]["recovered_amount"] == "95000.00"

    assert by_invoice["INV-SUNDIAL-4002"]["current_action"] == "TRACK_PROMISE_TO_PAY"


def test_recovery_case_detail_full_narrative(client):
    cases = client.get("/recovery-cases").json()
    vertex_id = next(c["id"] for c in cases if c["invoice_number"] == "INV-VERTEX-3010")

    resp = client.get(f"/recovery-cases/{vertex_id}")
    assert resp.status_code == 200
    body = resp.json()

    assert body["status"] == "ESCALATED"
    assert body["invoice"]["company"]["name"] == "Vertex Infra Solutions"
    assert len(body["actions"]) == 3
    assert body["actions"][-1]["action_type"] == "ESCALATE"
    assert body["actions"][-1]["policy_decisions"][0]["decision"] == "APPROVED"
    assert len(body["agent_decisions"]) == 2
    assert len(body["audit_logs"]) == 8
    assert body["audit_logs"] == sorted(body["audit_logs"], key=lambda a: a["occurred_at"])


def test_recovery_case_audit_trail_matches_detail(client):
    cases = client.get("/recovery-cases").json()
    case_id = cases[0]["id"]

    detail = client.get(f"/recovery-cases/{case_id}").json()
    trail = client.get(f"/recovery-cases/{case_id}/audit-trail").json()

    assert len(trail) == len(detail["audit_logs"])
    assert [a["id"] for a in trail] == [a["id"] for a in detail["audit_logs"]]


def test_promise_to_pay_case_has_pending_promise(client):
    cases = client.get("/recovery-cases").json()
    sundial_id = next(c["id"] for c in cases if c["invoice_number"] == "INV-SUNDIAL-4002")

    detail = client.get(f"/recovery-cases/{sundial_id}").json()
    assert len(detail["promises_to_pay"]) == 1
    assert detail["promises_to_pay"][0]["status"] == "PENDING"
    assert detail["promises_to_pay"][0]["promised_amount"] == "320000.00"


def test_recovery_case_404(client):
    resp = client.get(f"/recovery-cases/{NIL_UUID}")
    assert resp.status_code == 404

    resp = client.get(f"/recovery-cases/{NIL_UUID}/audit-trail")
    assert resp.status_code == 404


def test_dashboard_metrics_endpoint(client):
    resp = client.get("/dashboard/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert Decimal(data["total_revenue_at_risk"]) == Decimal("2780000.00")
    assert Decimal(data["total_revenue_recovered"]) == Decimal("95000.00")
    assert data["active_cases"] == 4
    assert data["escalated_cases"] == 1


def test_detect_overdue_endpoint_is_idempotent_against_seeded_data(client):
    # The seeded scenarios are already fully created (Phase 3 hand-seeds
    # cases directly), so the engine should find nothing new to do.
    resp = client.post("/recovery-cases/detect-overdue")
    assert resp.status_code == 200
    body = resp.json()
    assert body["invoices_marked_overdue"] == 0
    assert body["cases_created"] == 0
    assert body["case_ids"] == []
    # Sundial's seeded promise isn't due yet, so nothing should resolve either.
    assert body["promises_fulfilled"] == 0
    assert body["promises_broken"] == 0
