from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.llm_client import FALLBACK_MODEL_NAME, GEMINI_DEFAULT_MODEL, diagnose, recommend
from app.agents.schemas import DiagnosisResult, InterventionRecommendation
from app.core.config import settings

pytestmark = pytest.mark.asyncio(loop_scope="module")

_INVOICE = {"days_overdue": 5, "amount_total": 150000}
_CUSTOMER = {
    "num_prior_late_payments": 0,
    "num_prior_on_time_payments": 3,
}


async def test_no_keys_uses_rule_based_fallback(caplog):
    caplog.set_level("INFO", logger="app.llm")
    diagnosis, model = await diagnose(_INVOICE, _CUSTOMER)
    assert model == FALLBACK_MODEL_NAME
    assert diagnosis.recommended_priority == "low"

    rec, rec_model = await recommend(_INVOICE, _CUSTOMER, diagnosis.model_dump(), reminder_count=0)
    assert rec_model == FALLBACK_MODEL_NAME
    assert rec.action == "SEND_EMAIL"
    messages = [r.getMessage() for r in caplog.records]
    assert any("called=False" in m and "diagnose" in m for m in messages)


async def test_google_key_uses_gemini_default_model(monkeypatch):
    monkeypatch.setattr(settings, "google_api_key", "test-google-key")
    monkeypatch.setattr(settings, "openai_api_key", "test-openai-key")
    monkeypatch.setattr(settings, "llm_model", None)

    structured = MagicMock()
    structured.ainvoke = AsyncMock(
        return_value=DiagnosisResult(
            diagnosis="Gemini diagnosis",
            reason="mocked",
            recommended_priority="medium",
        )
    )
    chat = MagicMock()
    chat.with_structured_output.return_value = structured
    factory = MagicMock(return_value=chat)

    import langchain_google_genai

    monkeypatch.setattr(langchain_google_genai, "ChatGoogleGenerativeAI", factory)

    result, model = await diagnose(_INVOICE, _CUSTOMER)
    assert model == GEMINI_DEFAULT_MODEL
    assert result.diagnosis == "Gemini diagnosis"
    factory.assert_called_once()
    assert factory.call_args.kwargs["model"] == GEMINI_DEFAULT_MODEL
    assert factory.call_args.kwargs["api_key"] == "test-google-key"


async def test_openai_used_when_google_key_absent(monkeypatch):
    monkeypatch.setattr(settings, "google_api_key", None)
    monkeypatch.setattr(settings, "openai_api_key", "test-openai-key")
    monkeypatch.setattr(settings, "llm_model", None)

    structured = MagicMock()
    structured.ainvoke = AsyncMock(
        return_value=InterventionRecommendation(
            action="WAIT",
            rationale="mocked",
        )
    )
    chat = MagicMock()
    chat.with_structured_output.return_value = structured
    factory = MagicMock(return_value=chat)

    import langchain_openai

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", factory)

    rec, model = await recommend(_INVOICE, _CUSTOMER, {"diagnosis": "x"}, reminder_count=0)
    assert model == "gpt-4o-mini"
    assert rec.action == "WAIT"
    factory.assert_called_once()
    assert factory.call_args.kwargs["model"] == "gpt-4o-mini"
