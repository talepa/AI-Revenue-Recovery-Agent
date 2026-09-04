DIAGNOSIS_SYSTEM_PROMPT = """You are a B2B revenue-recovery analyst. Given structured data about an \
overdue invoice and the customer's payment history, diagnose the likely situation in one sentence \
plus a short supporting reason, and rate the priority as low, medium, or high. Do not recommend an \
action here — that happens separately. Be concise and factual; base your diagnosis only on the data \
provided, not assumptions."""

INTERVENTION_SYSTEM_PROMPT = """You are a B2B revenue-recovery analyst deciding the next action for an \
overdue invoice, given a diagnosis and how many reminders have already been sent. You MUST choose \
exactly one action from this fixed set: SEND_EMAIL, SEND_PAYMENT_LINK, TRACK_PROMISE_TO_PAY, ESCALATE, \
WAIT, CLOSE_CASE. A deterministic policy engine independently checks your recommendation against \
business rules before anything happens — you are recommending, not deciding. Give a one- to \
two-sentence rationale."""


def build_diagnosis_prompt(invoice_context: dict, customer_context: dict) -> str:
    return (
        f"Invoice: {invoice_context}\n"
        f"Customer payment history and features: {customer_context}\n\n"
        "Diagnose this case."
    )


def build_intervention_prompt(
    invoice_context: dict, customer_context: dict, diagnosis: dict, reminder_count: int
) -> str:
    return (
        f"Invoice: {invoice_context}\n"
        f"Customer context: {customer_context}\n"
        f"Diagnosis: {diagnosis}\n"
        f"Reminders already sent for this case: {reminder_count}\n\n"
        "Recommend the next action."
    )
