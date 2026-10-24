"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Anomaly } from "@/lib/types";
import { investigateQuestion, METRIC_LABELS, shortDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, PageHeader, SeverityPill } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

type Resp = {
  items: Anomaly[]; total: number; status_counts: Record<string, number>; sensitivity: string; detector: string;
  facets: { platforms: string[]; metrics: string[]; date_range: [string | null, string | null] };
};

const STATUSES = [
  { key: "new", label: "New" },
  { key: "investigating", label: "Investigating" },
  { key: "resolved", label: "Resolved" },
  { key: "not_actionable", label: "Not actionable" },
] as const;

const DQ: Record<string, string> = {
  ok: "OK",
  missing_data: "Missing rows",
  suspected_tracking_issue: "Suspected tracking issue",
  low_volume: "Low volume",
};

function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: Array<[string, string]> }) {
  const id = `f-${label.toLowerCase().replace(/\s/g, "-")}`;
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-xs text-muted-foreground">{label}</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className="h-8 rounded-md border bg-card px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring">
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </div>
  );
}

export default function AnomaliesPage() {
  const router = useRouter();
  const [f, setF] = useState({ status: "", severity: "", platform: "", metric: "", date_from: "", date_to: "" });
  const qs = useMemo(() => {
    const p = new URLSearchParams({ limit: "200" });
    Object.entries(f).forEach(([k, v]) => v && p.set(k, v));
    return p.toString();
  }, [f]);
  const { data, error, loading, reload, setData } = useApi<Resp>(`/api/anomalies?${qs}`);
  const set = (k: keyof typeof f) => (v: string) => setF((x) => ({ ...x, [k]: v }));

  const update = async (a: Anomaly, status: string) => {
    try {
      const r = await api<Anomaly>(`/api/anomalies/${a.id}`, { method: "PATCH", body: { status } });
      setData((d) => d && { ...d, items: d.items.map((x) => (x.id === a.id ? { ...x, status: r.status } : x)) });
      toast.success(`Marked ${STATUSES.find((s) => s.key === status)?.label.toLowerCase()}`);
      if (f.status && f.status !== status) void reload();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  return (
    <div>
      <PageHeader
        title="Anomaly Monitor"
        description={
          <>Statistical detections against a 28-day, day-of-week-adjusted baseline. A flag says a value is unusual, not why. Showing <b>{data?.sensitivity ?? "…"}</b> sensitivity (change it in Settings).</>
        }
      />
      <div className="mb-4 flex flex-wrap items-end gap-3 rounded-lg border bg-card p-3">
        <Select label="Status" value={f.status} onChange={set("status")} options={[["", "All"], ...STATUSES.map((s) => [s.key, s.label] as [string, string])]} />
        <Select label="Severity" value={f.severity} onChange={set("severity")} options={[["", "All"], ["high", "High"], ["medium", "Medium"], ["low", "Low"]]} />
        <Select label="Platform" value={f.platform} onChange={set("platform")} options={[["", "All"], ...(data?.facets.platforms ?? []).map((p) => [p, p] as [string, string])]} />
        <Select label="Metric" value={f.metric} onChange={set("metric")} options={[["", "All"], ...(data?.facets.metrics ?? []).map((m) => [m, METRIC_LABELS[m] ?? m] as [string, string])]} />
        <div className="flex flex-col gap-1">
          <label htmlFor="df" className="text-xs text-muted-foreground">From</label>
          <input id="df" type="date" value={f.date_from} onChange={(e) => set("date_from")(e.target.value)} className="h-8 rounded-md border bg-card px-2 text-sm" />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="dt" className="text-xs text-muted-foreground">To</label>
          <input id="dt" type="date" value={f.date_to} onChange={(e) => set("date_to")(e.target.value)} className="h-8 rounded-md border bg-card px-2 text-sm" />
        </div>
        {Object.values(f).some(Boolean) && (
          <Button variant="ghost" size="sm" onClick={() => setF({ status: "", severity: "", platform: "", metric: "", date_from: "", date_to: "" })}>Clear filters</Button>
        )}
        {data && <p className="ml-auto self-center text-sm text-muted-foreground">{data.total} detections</p>}
      </div>

      {error && <ErrorState error={error} onRetry={reload} />}
      {loading && !data && <Skeleton className="h-96 w-full" />}
      {data && data.items.length === 0 && <EmptyState title="No anomalies match these filters">Clear a filter or lower the sensitivity in Settings.</EmptyState>}
      {data && data.items.length > 0 && (
        <div className="overflow-x-auto rounded-lg border bg-card">
          <table className="w-full min-w-[1080px] text-sm" data-testid="anomaly-table">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="px-3 py-2 font-medium">Detected period</th>
                <th className="px-3 py-2 font-medium">Campaign</th>
                <th className="px-3 py-2 font-medium">Metric</th>
                <th className="px-3 py-2 text-right font-medium">Observed</th>
                <th className="px-3 py-2 text-right font-medium">Expected</th>
                <th className="px-3 py-2 text-right font-medium">Deviation</th>
                <th className="px-3 py-2 font-medium">Severity</th>
                <th className="px-3 py-2 font-medium">Data quality</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((a) => (
                <tr key={a.id} className={cn("border-b align-top last:border-0", a.status === "resolved" || a.status === "not_actionable" ? "text-muted-foreground" : "")}>
                  <td className="whitespace-nowrap px-3 py-2.5 tabular-nums">
                    {shortDate(a.anomaly_date)}{a.episode_days > 1 && ` – ${shortDate(a.episode_end)}`}
                    {a.episode_days > 1 && <span className="block text-xs text-muted-foreground">{a.episode_days} days</span>}
                  </td>
                  <td className="min-w-[170px] px-3 py-2.5"><span className="font-medium text-foreground">{a.campaign_name}</span><span className="block text-xs text-muted-foreground">{a.platform}</span></td>
                  <td className="px-3 py-2.5">{a.metric_label}<span className="block text-xs capitalize text-muted-foreground">{a.kind.replace("_", " ")}</span></td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">{a.observed_display}</td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">
                    {a.expected_display}
                    {a.expected_range_display && <span className="block text-xs text-muted-foreground">{a.expected_range_display}</span>}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">
                    {a.pct_deviation_display}
                    {a.robust_z !== null && <span className="block text-xs text-muted-foreground">z = {a.robust_z.toFixed(1)}</span>}
                  </td>
                  <td className="px-3 py-2.5"><SeverityPill severity={a.severity} /></td>
                  <td className="px-3 py-2.5 text-xs">{DQ[a.data_quality_status]}</td>
                  <td className="px-3 py-2.5">
                    <label className="sr-only" htmlFor={`st-${a.id}`}>Status for {a.campaign_name} {a.metric_label}</label>
                    <select id={`st-${a.id}`} value={a.status} onChange={(e) => void update(a, e.target.value)} className="h-7 rounded-md border bg-card px-1.5 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring">
                      {STATUSES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                    </select>
                  </td>
                  <td className="px-3 py-2.5">
                    <Button
                      variant="outline"
                      size="xs"
                      onClick={() => {
                        if (a.status === "new") void update(a, "investigating");
                        router.push(`/analyst?q=${encodeURIComponent(investigateQuestion(a))}`);
                      }}
                    >
                      Investigate
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && <p className="mt-3 text-xs text-muted-foreground">Detector {data.detector}. Status changes are saved to your account and are not shared with other users.</p>}
    </div>
  );
}
