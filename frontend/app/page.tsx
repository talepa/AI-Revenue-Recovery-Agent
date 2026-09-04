import { ActionButton } from "@/components/ActionButton";
import { BreakdownList } from "@/components/BreakdownList";
import { CasesTable } from "@/components/CasesTable";
import { MetricCard } from "@/components/MetricCard";
import { detectOverdueAction } from "@/app/actions";
import { riskTone } from "@/lib/badges";
import { ApiError, getDashboardMetrics, listRecoveryCases } from "@/lib/api";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/format";
import type { RecoveryActionType } from "@/lib/types";

const RISK_ORDER = ["LOW", "MEDIUM", "HIGH", "UNSCORED"] as const;

const ACTION_TONE: Record<RecoveryActionType, "blue" | "violet" | "orange" | "gray"> = {
  SEND_EMAIL: "blue",
  SEND_PAYMENT_LINK: "blue",
  TRACK_PROMISE_TO_PAY: "violet",
  ESCALATE: "orange",
  WAIT: "gray",
  CLOSE_CASE: "gray",
};

export default async function DashboardPage() {
  let metrics;
  let cases;
  try {
    [metrics, cases] = await Promise.all([getDashboardMetrics(), listRecoveryCases()]);
  } catch (err) {
    return (
      <div className="rounded-xl border border-rose-200 bg-rose-50 p-6 text-sm text-rose-700">
        <p className="font-semibold">Couldn&apos;t load the dashboard.</p>
        <p className="mt-1">{err instanceof ApiError ? err.message : "Unknown error."}</p>
      </div>
    );
  }

  const riskItems = RISK_ORDER.map((level) => ({
    label: level,
    count: metrics.cases_by_risk_level[level] ?? 0,
    tone: riskTone(level === "UNSCORED" ? null : level),
  }));

  const actionCounts = new Map<string, number>();
  for (const c of cases) {
    if (!c.current_action) continue;
    actionCounts.set(c.current_action, (actionCounts.get(c.current_action) ?? 0) + 1);
  }
  const actionItems = Array.from(actionCounts.entries()).map(([action, count]) => ({
    label: action,
    count,
    tone: ACTION_TONE[action as RecoveryActionType] ?? "gray",
  }));

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            Revenue Recovery Dashboard
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Live from the recovery engine — every number below reflects real database state.
          </p>
        </div>
        <ActionButton
          label="Run detection sweep"
          pendingLabel="Sweeping…"
          onRun={detectOverdueAction}
          variant="secondary"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <MetricCard label="Total Revenue at Risk" value={formatCurrency(metrics.total_revenue_at_risk)} />
        <MetricCard
          label="Total Revenue Recovered"
          value={formatCurrency(metrics.total_revenue_recovered)}
          tone="success"
        />
        <MetricCard
          label="Recovery Rate"
          value={formatPercent(metrics.recovery_rate)}
          caption="Recovered ÷ (recovered + still at risk)"
        />
        <MetricCard label="Active Cases" value={String(metrics.active_cases)} />
        <MetricCard
          label="Escalated Cases"
          value={String(metrics.escalated_cases)}
          tone={metrics.escalated_cases > 0 ? "danger" : "default"}
        />
        <MetricCard
          label="Avg. Days Overdue"
          value={metrics.average_days_overdue !== null ? `${formatNumber(metrics.average_days_overdue, 1)}d` : "—"}
          caption="Across active cases"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <BreakdownList title="Cases by Risk Level" items={riskItems} />
        <BreakdownList title="Recovery by Current Action" items={actionItems} />
      </div>

      <div>
        <h2 className="mb-3 text-sm font-semibold text-slate-900">Recovery Cases</h2>
        <CasesTable cases={cases} />
      </div>
    </div>
  );
}
