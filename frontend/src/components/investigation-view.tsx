"use client";

import { useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import {
  Bookmark, BookmarkCheck, Check, ChevronDown, Copy, Download, FileText, History, Pencil, RefreshCw, X,
} from "lucide-react";
import { api, download } from "@/lib/api";
import type { Analysis, Statement } from "@/lib/types";
import { changeTone, dateTime, formatMetric, METRIC_LABELS, shortDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ChartView } from "@/components/charts";
import { FactText } from "@/components/fact-text";
import { Delta, ModePill, Panel, StatusPill, SyntheticBadge } from "@/components/common";

const KIND = {
  observed: { label: "Observed facts", hint: "Read directly from the query result", cls: "bg-foreground" },
  calculated: { label: "Calculated contributions", hint: "Deterministic calculations on the result", cls: "bg-primary" },
  hypothesis: { label: "Possible explanations", hint: "Hypotheses to test, not findings", cls: "bg-caution" },
  action: { label: "Recommended actions", hint: "Next steps that follow from the evidence", cls: "bg-good" },
} as const;

function SectionTitle({ kind }: { kind: keyof typeof KIND }) {
  const k = KIND[kind];
  return (
    <div className="mb-3 flex items-baseline gap-2">
      <span className={cn("size-2 shrink-0 translate-y-[-1px] rounded-[2px]", k.cls)} aria-hidden />
      <h3 className="text-sm font-semibold">{k.label}</h3>
      <span className="text-xs text-muted-foreground">{k.hint}</span>
    </div>
  );
}

function StatementList({ items, kind }: { items: Statement[]; kind: keyof typeof KIND }) {
  if (!items.length) return <p className="text-sm text-muted-foreground">None for this question.</p>;
  return (
    <ul className="space-y-2.5">
      {items.map((s, i) => (
        <li key={i} className="text-[15px] leading-7">
          <FactText parts={s.parts} text={s.text} />
          {kind === "hypothesis" && s.confidence && (
            <span className="ml-2 text-xs text-muted-foreground">Confidence: {s.confidence}</span>
          )}
          {kind === "action" && s.rationale && <span className="block text-sm text-muted-foreground">{s.rationale}</span>}
        </li>
      ))}
    </ul>
  );
}

function KeyMetrics({ a }: { a: Analysis }) {
  const km = a.result?.calculations?.key_metrics;
  const p = a.result?.periods;
  if (!km?.length) return null;
  const compare = km[0].comparison !== undefined;
  return (
    <Panel title="Key metrics" action={p && <span className="text-xs text-muted-foreground">{compare && p.comparison ? `${p.current.label} vs ${p.comparison.label}` : p.current.label}</span>}>
      <div className="-mx-4 overflow-x-auto">
        <table className="w-full min-w-[560px] text-sm">
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground">
              <th className="px-4 py-2 font-medium">Metric</th>
              {compare && <th className="px-4 py-2 text-right font-medium">Comparison</th>}
              <th className="px-4 py-2 text-right font-medium">{compare ? "Current" : "Value"}</th>
              {compare && <th className="px-4 py-2 text-right font-medium">Change</th>}
              {compare && <th className="px-4 py-2 text-right font-medium">% change</th>}
            </tr>
          </thead>
          <tbody>
            {km.map((k) => (
              <tr key={k.metric} className={cn("border-b last:border-0", k.requested && "bg-accent/40")}>
                <td className="px-4 py-2 font-medium">{k.label}{k.requested && <span className="sr-only"> (asked about)</span>}</td>
                {compare && <td className="px-4 py-2 text-right tabular-nums">{k.comparison_display}</td>}
                <td className="px-4 py-2 text-right tabular-nums">{k.current_display}</td>
                {compare && <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">{k.abs_change_display}</td>}
                {compare && (
                  <td className="px-4 py-2 text-right">
                    <Delta display={k.pct_change_display ?? "n/a"} tone={changeTone(k.pct_change, k.higher_is_better)} />
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function RowsTable({ rows, cols }: { rows: Array<Record<string, unknown>>; cols: string[] }) {
  return (
    <div className="max-h-96 overflow-auto rounded-md border">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-muted">
          <tr>
            {cols.map((c) => (
              <th key={c} className="whitespace-nowrap px-3 py-2 text-left font-medium">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t">
              {cols.map((c) => {
                const v = r[c];
                const num = typeof v === "number";
                return (
                  <td key={c} className={cn("whitespace-nowrap px-3 py-1.5", num && "text-right tabular-nums")}>
                    {num ? formatMetric(c in METRIC_LABELS ? c : null, v) : String(v ?? "")}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Evidence({ a }: { a: Analysis }) {
  const r = a.result;
  if (!r) return null;
  const plan = a.plan as { filters?: Array<{ dimension: string; values: string[] }>; group_by?: string[]; metrics?: string[] } | null;
  const breakdown = r.calculations?.breakdown;
  const contribs = r.calculations?.contributions;
  const pm = r.calculations?.primary_metric;
  const anomalies = r.anomalies;
  return (
    <Panel title="Evidence">
      <dl className="mb-4 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        {r.periods && (
          <>
            <div><dt className="text-xs text-muted-foreground">Period</dt><dd>{r.periods.current.label}</dd></div>
            {r.periods.comparison && <div><dt className="text-xs text-muted-foreground">Compared with</dt><dd>{r.periods.comparison.label}</dd></div>}
          </>
        )}
        <div><dt className="text-xs text-muted-foreground">Filters</dt><dd>{plan?.filters?.length ? plan.filters.map((f) => `${f.dimension} = ${f.values.join(", ")}`).join("; ") : "None (all campaigns)"}</dd></div>
        <div><dt className="text-xs text-muted-foreground">Segments</dt><dd>{plan?.group_by?.length ? plan.group_by.join(", ") : "Totals only"}</dd></div>
        {r.periods?.anchor_date && <div className="sm:col-span-2"><dt className="text-xs text-muted-foreground">Date anchoring</dt><dd>Relative dates are anchored to the latest data date, {shortDate(r.periods.anchor_date)}.</dd></div>}
      </dl>
      <Tabs defaultValue={contribs && pm && contribs[pm] ? "contrib" : breakdown ? "breakdown" : anomalies ? "anomalies" : "rows"}>
        <TabsList>
          {contribs && pm && contribs[pm] && <TabsTrigger value="contrib">Segment contributions</TabsTrigger>}
          {breakdown && <TabsTrigger value="breakdown">Breakdown</TabsTrigger>}
          {anomalies && <TabsTrigger value="anomalies">Detections</TabsTrigger>}
          {r.rows && <TabsTrigger value="rows">Query result ({r.row_count} rows)</TabsTrigger>}
        </TabsList>
        {contribs && pm && contribs[pm] && (
          <TabsContent value="contrib" className="mt-3">
            <p className="mb-2 text-xs text-muted-foreground">Method: {contribs[pm].method}</p>
            <RowsTable
              cols={["segment", "comparison", "current", "pct_change", "contribution"]}
              rows={(contribs[pm].segments as Array<Record<string, number | string | null>>).map((s) => ({
                segment: s.label,
                comparison: formatMetric(pm, s.comparison),
                current: formatMetric(pm, s.current),
                pct_change: s.pct_change === null ? "n/a" : `${Number(s.pct_change).toFixed(1)}%`,
                contribution: formatMetric(pm, s.contribution),
              }))}
            />
          </TabsContent>
        )}
        {breakdown && (
          <TabsContent value="breakdown" className="mt-3">
            {r.calculations?.highlight_rule && <p className="mb-2 text-xs text-muted-foreground">{r.calculations.highlight_rule}</p>}
            <RowsTable
              cols={["rank", "label", ...(plan?.metrics ?? []), "share_spend", "flagged"]}
              rows={breakdown.map((b) => ({ ...b, share_spend: b.share_spend === null ? "n/a" : `${Number(b.share_spend).toFixed(1)}%`, flagged: b.flagged ? "Yes" : "" }))}
            />
          </TabsContent>
        )}
        {anomalies && (
          <TabsContent value="anomalies" className="mt-3">
            <RowsTable cols={["anomaly_date", "campaign_name", "metric", "kind", "severity", "pct_deviation"]} rows={anomalies.map((x) => ({ ...x, pct_deviation: x.pct_deviation === null ? "" : `${x.pct_deviation.toFixed(1)}%` }))} />
          </TabsContent>
        )}
        {r.rows && (
          <TabsContent value="rows" className="mt-3">
            <RowsTable rows={r.rows} cols={r.columns ?? Object.keys(r.rows[0] ?? {})} />
            {r.rows_stored !== undefined && r.row_count !== undefined && r.rows_stored < r.row_count && (
              <p className="mt-2 text-xs text-muted-foreground">Showing the first {r.rows_stored} of {r.row_count} rows stored with this investigation.</p>
            )}
          </TabsContent>
        )}
      </Tabs>
    </Panel>
  );
}

function SqlInspector({ a }: { a: Analysis }) {
  const [open, setOpen] = useState(false);
  const v = a.sql_validation;
  const steps = a.pipeline_trace?.steps ?? [];
  const attempts = a.pipeline_trace?.sql_attempts ?? [];
  const cc = a.result?.checks?.crosscheck;
  return (
    <section className="rounded-lg border bg-card">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span>
          <span className="text-sm font-semibold">SQL inspector and pipeline trace</span>
          <span className="ml-2 text-xs text-muted-foreground">
            {v?.skipped ? "No SQL: answered by the anomaly engine" : v?.ok ? `Validated, ${v.checks?.length ?? 0} checks passed, executed read-only` : v ? "Rejected by validator" : "Not reached"}
          </span>
        </span>
        <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="space-y-5 border-t p-4">
          {a.generated_sql && (
            <div>
              <div className="mb-2 flex items-center justify-between">
                <h4 className="text-xs font-medium text-muted-foreground">Executed SQL ({a.mode === "llm" ? "LLM-generated" : "built deterministically in demo mode"})</h4>
                <Button variant="ghost" size="xs" onClick={() => { void navigator.clipboard.writeText(a.generated_sql ?? ""); toast.success("SQL copied"); }}>
                  <Copy /> Copy
                </Button>
              </div>
              <pre className="max-h-80 overflow-auto rounded-md bg-muted p-3 font-mono text-xs leading-5" data-testid="sql">{a.generated_sql}</pre>
            </div>
          )}
          {v?.checks && (
            <div>
              <h4 className="mb-2 text-xs font-medium text-muted-foreground">Validation checks</h4>
              <ul className="grid gap-1 text-sm sm:grid-cols-2" data-testid="validation-checks">
                {v.checks.map((c) => (
                  <li key={c.check} className="flex items-start gap-2">
                    {c.passed ? <Check className="mt-0.5 size-4 text-good" aria-label="passed" /> : <X className="mt-0.5 size-4 text-bad" aria-label="failed" />}
                    <span>{c.check.replaceAll("_", " ")}{c.reason && <span className="block text-xs text-bad">{c.reason}</span>}</span>
                  </li>
                ))}
              </ul>
              {v.tables && <p className="mt-2 text-xs text-muted-foreground">Tables: {v.tables.join(", ")}. Row cap: {v.limit_applied}.</p>}
            </div>
          )}
          {cc && (
            <p className="text-sm">
              <span className="font-medium">Independent total cross-check: </span>
              {cc.matched === true ? "matched a deterministic reference query." : cc.note ?? "not run."}
            </p>
          )}
          {attempts.length > 1 && (
            <div>
              <h4 className="mb-2 text-xs font-medium text-muted-foreground">SQL attempts</h4>
              <ol className="space-y-1 text-sm">
                {attempts.map((t, i) => {
                  const val = t.validation as { ok: boolean; reasons: string[] } | undefined;
                  const rv = t.result_validation as { ok: boolean; problems?: string[] } | undefined;
                  return (
                    <li key={i}>
                      Attempt {String(t.attempt)}: {val?.ok === false ? `rejected (${val.reasons.join("; ")})` : rv?.ok === false ? `result check failed (${rv.problems?.join("; ")})` : "accepted"}
                    </li>
                  );
                })}
              </ol>
            </div>
          )}
          <div>
            <h4 className="mb-2 text-xs font-medium text-muted-foreground">Pipeline steps</h4>
            <ol className="space-y-1.5 text-sm" data-testid="pipeline-steps">
              {steps.map((s, i) => (
                <li key={i} className="flex gap-3">
                  <span className="w-5 shrink-0 text-right tabular-nums text-muted-foreground">{s.step}</span>
                  <span className="flex-1">
                    {s.name}
                    <span className={cn("ml-2 text-xs", s.status === "ok" ? "text-good" : s.status === "skipped" ? "text-muted-foreground" : "text-bad")}>{s.status}</span>
                    {typeof s.detail === "string" && <span className="block text-xs text-muted-foreground">{s.detail}</span>}
                  </span>
                  <span className="shrink-0 tabular-nums text-xs text-muted-foreground">{s.duration_ms} ms</span>
                </li>
              ))}
            </ol>
          </div>
          {a.llm_usage && (
            <p className="text-xs text-muted-foreground">
              LLM calls: {a.llm_usage.llm_calls}
              {a.llm_usage.llm_calls > 0 && `, ${a.llm_usage.input_tokens} input / ${a.llm_usage.output_tokens} output tokens, est. $${a.llm_usage.estimated_cost_usd.toFixed(4)}`}
              {a.explanation && `. Narrative numbers checked: ${a.explanation.verification.numeric_tokens_checked} literal, ${a.explanation.verification.fact_placeholders_rendered} fact chips.`}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

export function InvestigationView({
  a, onChange, onRefine, onRerun, rerunning,
}: { a: Analysis; onChange: (a: Analysis) => void; onRefine: (q: string) => void; onRerun: () => void; rerunning?: boolean }) {
  const e = a.explanation;
  const calc = a.result?.calculations;
  const stale = a.result_is_historical && a.current_data_as_of && a.data_as_of && a.current_data_as_of !== a.data_as_of;

  const toggleSave = async () => {
    const next = await api<Analysis>(`/api/analyses/${a.id}`, { method: "PATCH", body: { saved: !a.saved } });
    onChange({ ...next, result_is_historical: a.result_is_historical });
    toast.success(next.saved ? "Investigation saved" : "Removed from saved");
  };
  const saveReport = async () => {
    await api("/api/reports", { body: { analysis_id: a.id } });
    toast.success("Report saved", { description: "Find it under Reports." });
  };
  const copySummary = async () => {
    const text = [e?.summary.text, ...(e?.recommended_actions ?? []).map((x) => `- ${x.text}`)].filter(Boolean).join("\n");
    await navigator.clipboard.writeText(text || a.error_message || a.question);
    toast.success("Summary copied");
  };

  return (
    <article className="space-y-5" aria-label="Investigation result" data-testid="investigation">
      <header className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <StatusPill status={a.status} />
          <ModePill mode={a.mode} />
          {a.dataset_is_synthetic && <SyntheticBadge />}
          <span className="text-xs text-muted-foreground">
            {a.result_is_historical ? "Stored result" : "Fresh run"} from {dateTime(a.created_at)}
            {a.duration_ms !== null && `, ${(a.duration_ms / 1000).toFixed(2)} s`}
            {a.data_as_of && `, data through ${shortDate(a.data_as_of)}`}
          </span>
        </div>
        <h2 className="text-xl font-semibold leading-snug">{a.title && a.title !== a.question ? a.title : a.question}</h2>
        {a.title && a.title !== a.question && <p className="text-sm text-muted-foreground">{a.question}</p>}
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={onRerun} disabled={rerunning}>
            <RefreshCw className={cn(rerunning && "animate-spin")} /> {a.status === "succeeded" ? "Re-run on current data" : "Retry"}
          </Button>
          <Button variant="outline" size="sm" onClick={() => onRefine(a.question)}>
            <Pencil /> Refine question
          </Button>
          <Button variant="outline" size="sm" onClick={() => void toggleSave()} aria-pressed={a.saved}>
            {a.saved ? <BookmarkCheck className="text-primary" /> : <Bookmark />} {a.saved ? "Saved" : "Save investigation"}
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="outline" size="sm" />}>
              <Download /> Export <ChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              <DropdownMenuItem onClick={() => void download(`/api/analyses/${a.id}/export?format=markdown`, `investigation-${a.id}.md`)}>Markdown (.md)</DropdownMenuItem>
              <DropdownMenuItem onClick={() => void download(`/api/analyses/${a.id}/export?format=pdf`, `investigation-${a.id}.pdf`)}>PDF</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button variant="outline" size="sm" onClick={() => void saveReport()}>
            <FileText /> Save as report
          </Button>
          <Button variant="ghost" size="sm" onClick={() => void copySummary()}>
            <Copy /> Copy summary
          </Button>
        </div>
        {a.result_is_historical && (
          <p className="flex items-center gap-2 rounded-md border bg-muted/60 px-3 py-2 text-sm text-muted-foreground">
            <History className="size-4 shrink-0" aria-hidden />
            {stale
              ? `This stored result used data through ${shortDate(a.data_as_of)}. The dataset now runs through ${shortDate(a.current_data_as_of)}; re-run to refresh.`
              : "You are viewing a stored result. Re-run to query the database again."}
          </p>
        )}
      </header>

      {a.status !== "succeeded" && (
        <Panel title={a.status === "needs_clarification" ? "Clarification needed" : a.status === "unsupported" ? "Can't answer this from the data" : a.status === "rejected" ? "Request rejected" : "The analysis did not complete"}>
          <p className="text-[15px]">{a.error_message}</p>
          {a.result?.clarification_options && a.result.clarification_options.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {a.result.clarification_options.map((o) => (
                <Button key={o} variant="outline" size="sm" onClick={() => onRefine(o)}>{o}</Button>
              ))}
            </div>
          )}
          {a.status === "unsupported" && (
            <p className="mt-2 text-sm text-muted-foreground">
              The approved data has daily spend, impressions, clicks, conversions and revenue by campaign, platform and objective. <Link href="/data-sources" className="text-primary underline-offset-4 hover:underline">See the schema</Link>.
            </p>
          )}
        </Panel>
      )}

      {e && (
        <>
          <section aria-labelledby="answer" className="rounded-lg border bg-card p-5">
            <h3 id="answer" className="mb-2 text-sm font-semibold text-muted-foreground">Answer</h3>
            <p className="text-[17px] leading-8" data-testid="summary">
              <FactText parts={e.summary.parts} text={e.summary.text} />
            </p>
            <p className="mt-3 text-xs text-muted-foreground">
              {e.source === "llm" && "Written by the LLM from verified facts. "}
              {e.source === "deterministic" && (a.mode === "demo" ? "Template narrative (demo mode). " : "Deterministic narrative. ")}
              {e.source === "deterministic_fallback" && "The LLM draft failed number verification, so a deterministic narrative is shown. "}
              Highlighted numbers come from the query result; hover one to see its source.
            </p>
          </section>

          <KeyMetrics a={a} />

          {calc?.charts && calc.charts.length > 0 && (
            <Panel title="Charts">
              <div className={cn("grid gap-8", calc.charts.length > 1 && "xl:grid-cols-2")} data-testid="charts">
                {calc.charts.map((c, i) => <ChartView key={i} spec={c} />)}
              </div>
            </Panel>
          )}

          <div className="grid gap-5 lg:grid-cols-2">
            <section className="rounded-lg border bg-card p-4"><SectionTitle kind="observed" /><StatementList items={e.observed_facts} kind="observed" /></section>
            <section className="rounded-lg border bg-card p-4"><SectionTitle kind="calculated" /><StatementList items={e.contributions} kind="calculated" /></section>
            <section className="rounded-lg border border-dashed border-caution/50 bg-card p-4"><SectionTitle kind="hypothesis" /><StatementList items={e.possible_explanations} kind="hypothesis" /></section>
            <section className="rounded-lg border bg-card p-4"><SectionTitle kind="action" /><StatementList items={e.recommended_actions} kind="action" /></section>
          </div>

          <Panel title="Limitations and assumptions">
            <ul className="list-disc space-y-1.5 pl-5 text-sm" data-testid="limitations">
              {[...new Set([...(e.computed_limitations ?? []), ...(e.limitations ?? [])])].map((l, i) => <li key={i}>{l}</li>)}
            </ul>
          </Panel>
        </>
      )}

      <Evidence a={a} />
      <SqlInspector a={a} />
    </article>
  );
}
