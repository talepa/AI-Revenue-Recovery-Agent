"""LLM provider abstraction with a deterministic fallback.

If OPENAI_API_KEY is configured (backend/.env), diagnosis/intervention use a
real OpenAI-compatible chat model via LangChain's structured output. If not,
a deterministic rule-based fallback produces plausible results so the whole
graph is fully runnable and testable with zero external dependencies or
cost. Swapping providers is a config change, not a code change.
"""

from app.agents.prompts import (
    DIAGNOSIS_SYSTEM_PROMPT,
    INTERVENTION_SYSTEM_PROMPT,
    build_diagnosis_prompt,
    build_intervention_prompt,
)
from app.agents.schemas import DiagnosisResult, InterventionRecommendation
from app.core.config import settings

FALLBACK_MODEL_NAME = "rule-based-fallback"


def _llm_configured() -> bool:
    return bool(settings.openai_api_key)


async def diagnose(invoice_context: dict, customer_context: dict) -> tuple[DiagnosisResult, str]:
    if _llm_configured():
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model=settings.llm_model, api_key=settings.openai_api_key, temperature=0)
        structured_llm = llm.with_structured_output(DiagnosisResult)
        messages = [
            SystemMessage(content=DIAGNOSIS_SYSTEM_PROMPT),
            HumanMessage(content=build_diagnosis_prompt(invoice_context, customer_context)),
        ]
        result = await structured_llm.ainvoke(messages)
        return result, settings.llm_model

    return _rule_based_diagnosis(invoice_context, customer_context), FALLBACK_MODEL_NAME


async def recommend(
    invoice_context: dict, customer_context: dict, diagnosis: dict, reminder_count: int
) -> tuple[InterventionRecommendation, str]:
    if _llm_configured():
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model=settings.llm_model, api_key=settings.openai_api_key, temperature=0)
        structured_llm = llm.with_structured_output(InterventionRecommendation)
        messages = [
            SystemMessage(content=INTERVENTION_SYSTEM_PROMPT),
            HumanMessage(
                content=build_intervention_prompt(invoice_context, customer_context, diagnosis, reminder_count)
            ),
        ]
        result = await structured_llm.ainvoke(messages)
        return result, settings.llm_model

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
