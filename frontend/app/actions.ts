"use server";

import { revalidatePath } from "next/cache";
import { ApiError, detectOverdue, runRecoveryCase, simulatePayment } from "@/lib/api";

export type ActionResult = { ok: true } | { ok: false; error: string };

export async function runRecoveryCaseAction(caseId: string): Promise<ActionResult> {
  try {
    await runRecoveryCase(caseId);
    revalidatePath(`/cases/${caseId}`);
    revalidatePath("/");
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err instanceof ApiError ? err.message : "Something went wrong." };
  }
}

export async function detectOverdueAction(): Promise<ActionResult> {
  try {
    await detectOverdue();
    revalidatePath("/");
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err instanceof ApiError ? err.message : "Something went wrong." };
  }
}

export async function simulatePaymentAction(
  invoiceId: string,
  caseId: string,
): Promise<ActionResult> {
  try {
    await simulatePayment(invoiceId);
    revalidatePath(`/cases/${caseId}`);
    revalidatePath("/");
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err instanceof ApiError ? err.message : "Something went wrong." };
  }
}
