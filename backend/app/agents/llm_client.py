"""LLM provider abstraction with a deterministic fallback.

If GOOGLE_API_KEY or OPENAI_API_KEY is configured (backend/.env), diagnosis
and intervention use a real chat model via LangChain structured output.
Gemini is preferred when both keys are set. If neither key is set, a
deterministic rule-based fallback produces plausible results so the whole
graph is fully runnable and testable with zero external dependencies or
cost. Presence of a key is the switch — no separate feature flag.
"""

import logging
from typing import Any

from app.agents.prompts import (
    DIAGNOSIS_SYSTEM_PROMPT,
    INTERVENTION_SYSTEM_PROMPT,
    build_diagnosis_prompt,
    build_intervention_prompt,
)
from app.agents.schemas import DiagnosisResult, InterventionRecommendation
from app.core.config import settings

FALLBACK_MODEL_NAME = "rule-based-fallback"
GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"
OPENAI_DEFAULT_MODEL = "gpt-4o-mini"

logger = logging.getLogger("app.llm")


def configured_llm() -> tuple[str, str]:
    """Return (provider, model_name) without constructing a client."""
    if settings.google_api_key:
        return "gemini", settings.llm_model or GEMINI_DEFAULT_MODEL
    if settings.openai_api_key:
        return "openai", settings.llm_model or OPENAI_DEFAULT_MODEL
    return "fallback", FALLBACK_MODEL_NAME


def _llm_chat() -> tuple[Any, str] | tuple[None, None]:
    provider, model = configured_llm()
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return (
            ChatGoogleGenerativeAI(
                model=model,
                api_key=settings.google_api_key,
                temperature=0,
            ),
            model,
        )
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return (
            ChatOpenAI(model=model, api_key=settings.openai_api_key, temperature=0),
            model,
        )
    return None, None


def _log_llm_call(stage: str, provider: str, model_name: str, *, llm_called: bool) -> None:
    logger.info(
        "llm %s provider=%s model=%s called=%s",
        stage,
        provider,
        model_name,
        llm_called,
        extra={
            "stage": stage,
            "provider": provider,
            "model": model_name,
            "llm_called": llm_called,
        },
    )


async def diagnose(invoice_context: dict, customer_context: dict) -> tuple[DiagnosisResult, str]:
    provider, _configured_model = configured_llm()
    llm, model_name = _llm_chat()
    if llm is not None:
        from langchain_core.messages import HumanMessage, SystemMessage

        structured_llm = llm.with_structured_output(DiagnosisResult)
        messages = [
            SystemMessage(content=DIAGNOSIS_SYSTEM_PROMPT),
            HumanMessage(content=build_diagnosis_prompt(invoice_context, customer_context)),
        ]
        result = await structured_llm.ainvoke(messages)
        _log_llm_call("diagnose", provider, model_name, llm_called=True)
        return result, model_name

    _log_llm_call("diagnose", provider, FALLBACK_MODEL_NAME, llm_called=False)
    return _rule_based_diagnosis(invoice_context, customer_context), FALLBACK_MODEL_NAME


async def recommend(
    invoice_context: dict, customer_context: dict, diagnosis: dict, reminder_count: int
) -> tuple[InterventionRecommendation, str]:
    provider, _configured_model = configured_llm()
    llm, model_name = _llm_chat()
    if llm is not None:
        from langchain_core.messages import HumanMessage, SystemMessage

        structured_llm = llm.with_structured_output(InterventionRecommendation)
        messages = [
            SystemMessage(content=INTERVENTION_SYSTEM_PROMPT),
            HumanMessage(
                content=build_intervention_prompt(invoice_context, customer_context, diagnosis, reminder_count)
            ),
        ]
        result = await structured_llm.ainvoke(messages)
        _log_llm_call("recommend", provider, model_name, llm_called=True)
        return result, model_name

    _log_llm_call("recommend", provider, FALLBACK_MODEL_NAME, llm_called=False)
    return _rule_based_intervention(invoice_context, reminder_count), FALLBACK_MODEL_NAME


def _rule_based_diagnosis(invoice_context: dict, customer_context: dict) -> DiagnosisResult:
    days_overdue = invoice_context["days_overdue"]
    num_late = customer_context["num_prior_late_payments"]
    num_on_time = customer_context["num_prior_on_time_payments"]
    promise = customer_context.get("promise_to_pay")

    if promise and promise["status"] == "BROKEN":
        return DiagnosisResult(
            diagnosis="Customer broke a promised payment date",
            reason=(
                f"Promised ₹{promise['promised_amount']:,.2f} by {promise['promised_date']}, "
                f"which passed without payment."
            ),
            recommended_priority="high",
        )

    if num_late >= 2 and num_late > num_on_time:
        return DiagnosisResult(
            diagnosis="Recurring late-payment pattern",
            reason=f"Customer paid late in {num_late} of the last {num_late + num_on_time} invoices.",
            recommended_priority="high" if days_overdue > 45 else "medium",
        )
    if days_overdue > 45:
        return DiagnosisResult(
            diagnosis="Significantly overdue with limited resolution",
            reason=f"Invoice is {days_overdue} days overdue.",
            recommended_priority="high",
        )
    return DiagnosisResult(
        diagnosis="Isolated late payment",
        reason="Customer has a largely clean payment history; likely an administrative delay.",
        recommended_priority="low",
    )


def _rule_based_intervention(invoice_context: dict, reminder_count: int) -> InterventionRecommendation:
    if invoice_context["days_overdue"] > 45 and invoice_context["amount_total"] >= 1_000_000:
        return InterventionRecommendation(
            action="ESCALATE", rationale="High-value invoice significantly overdue."
        )
    if reminder_count == 0:
        return InterventionRecommendation(
            action="SEND_EMAIL", rationale="First reminder for a newly overdue invoice."
        )
    if reminder_count == 1:
        return InterventionRecommendation(
            action="SEND_PAYMENT_LINK",
            rationale="No response to the first reminder; lower friction to pay.",
        )
    return InterventionRecommendation(
        action="ESCALATE", rationale="Multiple reminders sent without payment."
    )
