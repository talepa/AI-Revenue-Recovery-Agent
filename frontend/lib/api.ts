import type {
  DashboardMetrics,
  DetectionSummary,
  Invoice,
  PolicyOverrideStats,
  RecoveryCaseDetail,
  RecoveryCaseListItem,
} from "./types";

// Server-only — never exposed to the browser (no NEXT_PUBLIC_ prefix). All
// data fetching and mutations happen in Server Components / Server Actions,
// so the browser never talks to the backend directly and no CORS setup is
// needed on the API.
// 127.0.0.1 (IPv4) — `localhost` can resolve to ::1 and hit a Docker listener
// on :8000 instead of the local uvicorn process.
const API_BASE_URL = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    public status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(
      `Could not reach the API at ${API_BASE_URL}. Is the backend running? (try ./run.sh)`,
    );
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError(body.detail ?? `Request to ${path} failed`, response.status);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const getDashboardMetrics = () => apiFetch<DashboardMetrics>("/dashboard/metrics");

export const getPolicyOverrideStats = () =>
  apiFetch<PolicyOverrideStats>("/dashboard/policy-overrides");

export const listRecoveryCases = () => apiFetch<RecoveryCaseListItem[]>("/recovery-cases");

export const getRecoveryCase = (id: string) =>
  apiFetch<RecoveryCaseDetail>(`/recovery-cases/${id}`);

export const listOverdueInvoices = () => apiFetch<Invoice[]>("/invoices/overdue");

export const runRecoveryCase = (id: string) =>
  apiFetch<RecoveryCaseDetail>(`/recovery-cases/${id}/run`, { method: "POST" });

export const detectOverdue = () =>
  apiFetch<DetectionSummary>("/recovery-cases/detect-overdue", { method: "POST" });

export const simulatePayment = (invoiceId: string, amount?: string) =>
  apiFetch<Invoice>(`/invoices/${invoiceId}/simulate-payment`, {
    method: "POST",
    body: amount ? JSON.stringify({ amount }) : undefined,
  });
