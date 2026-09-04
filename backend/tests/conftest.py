"""Keep local .env LLM keys from changing the deterministic test path.

Workflow tests assert the rule-based fallback's first-cycle SEND_EMAIL
behavior. A real GOOGLE_API_KEY in backend/.env must not make those
tests call Gemini.
"""

import pytest

from app.core.config import settings


@pytest.fixture(autouse=True)
def disable_external_llm(monkeypatch):
    monkeypatch.setattr(settings, "google_api_key", None)
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "llm_model", None)
