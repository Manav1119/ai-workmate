// Display helpers. Metric values arrive pre-formatted from the backend where it matters
// (facts, KPIs); these helpers cover chart axes and tables built from raw rows.

const UNITS: Record<string, "currency" | "count" | "percent" | "multiple"> = {
  spend: "currency",
  revenue: "currency",
  cpa: "currency",
  cpc: "currency",
  aov: "currency",
  impressions: "count",
  clicks: "count",
  conversions: "count",
  conversion_rate: "percent",
  ctr: "percent",
  roas: "multiple",
};

export const METRIC_LABELS: Record<string, string> = {
  spend: "Spend",
  revenue: "Revenue",
  cpa: "CPA",
  cpc: "CPC",
  aov: "AOV",
  impressions: "Impressions",
  clicks: "Clicks",
  conversions: "Conversions",
  conversion_rate: "Conversion rate",
  ctr: "CTR",
  roas: "ROAS",
  data_completeness: "Data completeness",
};

export function unitOf(metric: string | null | undefined) {
  return (metric && UNITS[metric]) || "count";
}

export function formatMetric(metric: string | null | undefined, v: unknown, opts: { compact?: boolean } = {}): string {
  if (v === null || v === undefined || v === "" || Number.isNaN(Number(v))) return "n/a";
  const n = Number(v);
  const unit = unitOf(metric);
  if (unit === "percent") return `${(n * 100).toFixed(2)}%`;
  if (unit === "multiple") return `${n.toFixed(2)}x`;
  const compact = opts.compact && Math.abs(n) >= 10000;
  const nf = new Intl.NumberFormat("en-US", {
    notation: compact ? "compact" : "standard",
    maximumFractionDigits: opts.compact ? (compact ? 1 : 0) : unit === "currency" ? 2 : 0,
    minimumFractionDigits: unit === "currency" && !opts.compact ? 2 : 0,
  });
  const s = nf.format(Math.abs(n));
  const sign = n < 0 ? "−" : "";
  return unit === "currency" ? `${sign}$${s}` : `${sign}${s}`;
}

export function formatSigned(metric: string | null | undefined, v: number | null | undefined): string {
  if (v === null || v === undefined) return "n/a";
  const base = formatMetric(metric, Math.abs(v));
  return `${v > 0 ? "+" : v < 0 ? "−" : "±"}${base}`;
}

/** Whether a change is good for the business, given the metric's direction. */
export function changeTone(pct: number | null | undefined, higherIsBetter: boolean | undefined): "good" | "bad" | "neutral" {
  if (pct === null || pct === undefined || Math.abs(pct) < 0.05) return "neutral";
  const up = pct > 0;
  return up === (higherIsBetter ?? true) ? "good" : "bad";
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "n/a";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "n/a";
  return new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function relativeTime(iso: string, now: Date = new Date()): string {
  const s = Math.round((now.getTime() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  const d = Math.floor(s / 86400);
  return d === 1 ? "yesterday" : `${d} days ago`;
}

export function greeting(now: Date = new Date()): string {
  const h = now.getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

export const STATUS_LABEL: Record<string, string> = {
  succeeded: "Answered",
  failed: "Failed",
  needs_clarification: "Needs clarification",
  unsupported: "Not answerable",
  rejected: "Rejected",
  running: "Running",
};

/** The follow-up question asked when a user clicks "Investigate" on an anomaly. */
export function investigateQuestion(a: { kind: string; metric_label: string; campaign_name: string; anomaly_date: string; episode_end: string }): string {
  const metric = a.kind === "missing_data" ? "spend" : a.metric_label.toLowerCase();
  return `Why did ${metric} change for ${a.campaign_name} from ${a.anomaly_date} to ${a.episode_end}?`;
}
