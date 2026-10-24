"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useSession } from "@/components/session";
import { useApi } from "@/lib/hooks";
import type { Overview } from "@/lib/types";
import { changeTone, greeting, investigateQuestion, relativeTime, shortDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { AskBar } from "@/components/ask-bar";
import { ChartView } from "@/components/charts";
import {
  Delta, EmptyState, ErrorState, FreshnessIndicator, ModePill, Panel, SeverityPill, StatusPill, SyntheticBadge,
} from "@/components/common";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";

const SERIES_OPTIONS = [
  { key: "conversions", label: "Conversions", pair: "spend" },
  { key: "revenue", label: "Revenue", pair: "spend" },
  { key: "cpa", label: "CPA", pair: "conversions" },
  { key: "roas", label: "ROAS", pair: "spend" },
];

export default function OverviewPage() {
  const { user } = useSession();
  const router = useRouter();
  const [days, setDays] = useState(7);
  const [metric, setMetric] = useState("conversions");
  const { data, error, loading, reload } = useApi<Overview>(`/api/metrics/overview?days=${days}&series_days=60`);

  const ask = (q: string) => router.push(`/analyst?q=${encodeURIComponent(q)}`);
  const opt = SERIES_OPTIONS.find((o) => o.key === metric)!;

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">{greeting()}, {user?.display_name.split(" ")[0]}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-3">
            {data && <FreshnessIndicator f={data.freshness} />}
            {data?.dataset.is_synthetic && <SyntheticBadge />}
            {data && <span className="text-sm text-muted-foreground">{data.dataset.name}</span>}
          </div>
        </div>
      </header>

      <AskBar onAsk={ask} compact />

      {error && <ErrorState error={error} onRetry={reload} />}
      {loading && !data && (
        <div className="space-y-4">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-80 w-full" />
        </div>
      )}
      {data?.empty && (
        <EmptyState title="This dataset has no rows yet" action={<Button render={<Link href="/data-sources" />}>Import a CSV</Button>}>
          Upload campaign data or switch back to the synthetic demo dataset in Data Sources.
        </EmptyState>
      )}

      {data && !data.empty && (
        <>
          <section aria-labelledby="kpis">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <h2 id="kpis" className="text-sm font-semibold">
                {data.period?.label} <span className="font-normal text-muted-foreground">vs previous {days} days</span>
              </h2>
              <div role="group" aria-label="Comparison window" className="inline-flex rounded-md border bg-card p-0.5">
                {[7, 14, 28].map((d) => (
                  <button
                    key={d}
                    type="button"
                    aria-pressed={days === d}
                    onClick={() => setDays(d)}
                    className={cn("rounded px-2.5 py-1 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring", days === d ? "bg-secondary font-medium" : "text-muted-foreground")}
                  >
                    {d} days
                  </button>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border sm:grid-cols-3 xl:grid-cols-6" data-testid="kpi-strip">
              {data.kpis.map((k) => (
                <div key={k.metric} className="bg-card p-4">
                  <p className="text-xs text-muted-foreground">{k.label}</p>
                  <p className="mt-1 text-xl font-semibold tabular-nums">{k.current_display}</p>
                  <p className="mt-0.5 text-xs">
                    <Delta display={k.pct_change_display} tone={changeTone(k.pct_change, k.higher_is_better)} />
                    <span className="ml-1 text-muted-foreground">from {k.comparison_display}</span>
                  </p>
                </div>
              ))}
            </div>
          </section>

          <Panel
            title="Daily performance, last 60 days"
            action={
              <div role="group" aria-label="Chart metric" className="inline-flex flex-wrap rounded-md border p-0.5">
                {SERIES_OPTIONS.map((o) => (
                  <button key={o.key} type="button" aria-pressed={metric === o.key} onClick={() => setMetric(o.key)}
                    className={cn("rounded px-2.5 py-1 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring", metric === o.key ? "bg-secondary font-medium" : "text-muted-foreground")}>
                    {o.label}
                  </button>
                ))}
              </div>
            }
          >
            <ChartView
              height={300}
              spec={{
                type: "line", title: `${opt.label} with ${opt.pair} for context`, x_key: "date", unit_metric: metric,
                series: [{ key: metric, label: opt.label, unit_metric: metric }, { key: opt.pair, label: opt.pair[0].toUpperCase() + opt.pair.slice(1), unit_metric: opt.pair }],
                data: data.series,
              }}
            />
          </Panel>

          <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
            <Panel title="Anomalies needing investigation" action={<Link href="/anomalies" className="text-sm text-primary underline-offset-4 hover:underline">Open monitor ({data.anomalies_open_count})</Link>}>
              {data.anomalies.length === 0 ? (
                <EmptyState title="Nothing open in the last 28 days">New statistical anomalies will appear here.</EmptyState>
              ) : (
                <ul className="-my-2 divide-y">
                  {data.anomalies.map((a) => (
                    <li key={a.id} className="flex items-start justify-between gap-3 py-2.5">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium">{a.campaign_name}</p>
                        <p className="text-xs text-muted-foreground">
                          {a.metric_label} {a.kind.replace("_", " ")} from {shortDate(a.anomaly_date)}
                          {a.kind === "drop" || a.kind === "spike" ? `, ${a.pct_deviation_display} vs expected` : ""}
                        </p>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <SeverityPill severity={a.severity} />
                        <Button variant="ghost" size="xs" onClick={() => ask(investigateQuestion(a))}>
                          Investigate
                        </Button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
            <Panel title="Recent investigations" action={<Link href="/history" className="text-sm text-primary underline-offset-4 hover:underline">All history</Link>}>
              {data.recent_investigations.length === 0 ? (
                <EmptyState title="No investigations yet">Ask a question above to start one.</EmptyState>
              ) : (
                <ul className="-my-2 divide-y">
                  {data.recent_investigations.map((r) => (
                    <li key={r.id} className="py-2.5">
                      <Link href={`/analyst?id=${r.id}`} className="block rounded outline-none hover:text-primary focus-visible:ring-2 focus-visible:ring-ring">
                        <p className="truncate text-sm font-medium">{r.question}</p>
                        <p className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                          <StatusPill status={r.status} /> <ModePill mode={r.mode as "llm" | "demo"} /> {relativeTime(r.created_at)}
                        </p>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
