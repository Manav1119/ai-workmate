"use client";

import { useState } from "react";
import { toast } from "sonner";
import { CheckCircle2, Loader2, Trash2, Upload } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Connector, Dataset } from "@/lib/types";
import { formatMetric, shortDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useSession } from "@/components/session";
import { ErrorState, FreshnessIndicator, PageHeader, Panel, SyntheticBadge } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";

type Staged = {
  upload_id: string; filename: string; rows: number;
  columns: Array<{ name: string; inferred_type: string; missing: number; sample: string[] }>;
  suggested_mapping: Record<string, string | null>;
  targets: Record<string, { required: boolean; type: string }>;
  preview: Array<Record<string, unknown>>;
};
type Summary = {
  dataset_id: number; rows_imported: number; campaigns: number; date_range: [string, string]; anomalies_detected: number;
  missing_values: Record<string, number>; duplicate_rows: number; warnings: string[];
};
type Schema = { tables: Array<{ name: string; columns: Array<{ name: string; type: string; description: string }> }>; relationships: string[] };
type Metric = { key: string; label: string; definition: string; formula: string; zero_handling: string };

function Importer({ onDone }: { onDone: () => void }) {
  const { user } = useSession();
  const [staged, setStaged] = useState<Staged | null>(null);
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const [name, setName] = useState("");
  const [tz, setTz] = useState(user?.reporting_timezone ?? "UTC");
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<{ message: string; details: string[] } | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);

  const upload = async (file: File) => {
    setBusy(true);
    setErrors(null);
    setSummary(null);
    const fd = new FormData();
    fd.append("file", file);
    try {
      const s = await api<Staged>("/api/data-sources/upload", { form: fd });
      setStaged(s);
      setMapping(s.suggested_mapping);
      setName(file.name.replace(/\.csv$/i, ""));
    } catch (e) {
      setErrors({ message: (e as Error).message, details: [] });
    } finally {
      setBusy(false);
    }
  };
  const doImport = async () => {
    if (!staged) return;
    setBusy(true);
    setErrors(null);
    try {
      const s = await api<Summary>(`/api/data-sources/imports/${staged.upload_id}`, { body: { mapping, dataset_name: name, reporting_timezone: tz } });
      setSummary(s);
      setStaged(null);
      toast.success("Import complete");
      onDone();
    } catch (e) {
      const err = e as ApiError;
      setErrors({ message: err.message, details: Array.isArray(err.details) ? (err.details as unknown[]).map(String) : [] });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title="Import a CSV">
      <p className="mb-3 text-sm text-muted-foreground">
        One row per campaign per day with date, campaign, spend, impressions, clicks, conversions and revenue. Up to 10 MB.
        Files are validated before anything is stored; uploads are private to your account.
      </p>
      <label className={cn("flex cursor-pointer items-center justify-center gap-2 rounded-lg border border-dashed px-4 py-6 text-sm hover:border-primary/50", busy && "opacity-60")}>
        {busy ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
        <span>{staged ? `${staged.filename}: ${staged.rows} rows. Choose another file` : "Choose a CSV file"}</span>
        <input type="file" accept=".csv,text/csv" className="sr-only" disabled={busy} onChange={(e) => e.target.files?.[0] && void upload(e.target.files[0])} />
      </label>
      {errors && (
        <div role="alert" className="mt-3 rounded-md border border-bad/30 bg-bad/5 p-3 text-sm">
          <p className="font-medium text-bad">{errors.message}</p>
          {errors.details.length > 0 && <ul className="mt-1 list-disc pl-5">{errors.details.map((d) => <li key={d}>{d}</li>)}</ul>}
        </div>
      )}
      {staged && (
        <div className="mt-4 space-y-4">
          <div>
            <h3 className="mb-2 text-sm font-semibold">Column mapping</h3>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {Object.entries(staged.targets).map(([t, spec]) => (
                <div key={t} className="flex flex-col gap-1">
                  <label htmlFor={`map-${t}`} className="text-xs text-muted-foreground">{t}{spec.required ? " (required)" : ""}, {spec.type}</label>
                  <select id={`map-${t}`} value={mapping[t] ?? ""} onChange={(e) => setMapping({ ...mapping, [t]: e.target.value || null })} className="h-8 rounded-md border bg-card px-2 text-sm">
                    <option value="">Not mapped</option>
                    {staged.columns.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
                  </select>
                </div>
              ))}
            </div>
          </div>
          <div>
            <h3 className="mb-2 text-sm font-semibold">Detected columns</h3>
            <div className="overflow-x-auto rounded-md border">
              <table className="w-full text-xs">
                <thead className="bg-muted"><tr><th className="px-2 py-1.5 text-left">Column</th><th className="px-2 py-1.5 text-left">Inferred type</th><th className="px-2 py-1.5 text-right">Missing</th><th className="px-2 py-1.5 text-left">Sample</th></tr></thead>
                <tbody>{staged.columns.map((c) => <tr key={c.name} className="border-t"><td className="px-2 py-1.5 font-medium">{c.name}</td><td className="px-2 py-1.5">{c.inferred_type}</td><td className={cn("px-2 py-1.5 text-right", c.missing > 0 && "text-caution")}>{c.missing}</td><td className="px-2 py-1.5 text-muted-foreground">{c.sample.join(", ")}</td></tr>)}</tbody>
              </table>
            </div>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex min-w-[220px] flex-1 flex-col gap-1">
              <label htmlFor="dsname" className="text-xs text-muted-foreground">Dataset name</label>
              <Input id="dsname" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="dstz" className="text-xs text-muted-foreground">Reporting timezone (for timestamps)</label>
              <Input id="dstz" value={tz} onChange={(e) => setTz(e.target.value)} className="w-56" />
            </div>
            <Button onClick={() => void doImport()} disabled={busy || !name || !!user?.is_demo}>
              {busy && <Loader2 className="animate-spin" />} Validate and import
            </Button>
          </div>
          {user?.is_demo && <p className="text-sm text-caution">The shared demo account can check a file here, but storing data needs your own account.</p>}
        </div>
      )}
      {summary && (
        <div className="mt-4 rounded-md border border-good/30 bg-good/5 p-3 text-sm" role="status">
          <p className="flex items-center gap-2 font-medium text-good"><CheckCircle2 className="size-4" /> Imported {summary.rows_imported} rows across {summary.campaigns} campaigns</p>
          <p className="mt-1">Dates {summary.date_range[0]} to {summary.date_range[1]}. Duplicates: {summary.duplicate_rows}. Anomalies detected: {summary.anomalies_detected}.</p>
          {summary.warnings.length > 0 && <ul className="mt-1 list-disc pl-5 text-muted-foreground">{summary.warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
        </div>
      )}
    </Panel>
  );
}

export default function DataSourcesPage() {
  const { refresh } = useSession();
  const { data, error, loading, reload } = useApi<{ items: Dataset[]; connectors: Connector[] }>("/api/data-sources");
  const schema = useApi<Schema>("/api/schema");
  const metrics = useApi<{ metrics: Metric[] }>("/api/metric-definitions");
  const [previewId, setPreviewId] = useState<number | null>(null);
  const preview = useApi<{ campaigns: Array<Record<string, string>>; recent_rows: Array<Record<string, number | string>> }>(previewId ? `/api/data-sources/${previewId}/preview` : null);

  const activate = async (id: number) => {
    await api("/api/auth/me", { method: "PATCH", body: { active_dataset_id: id } });
    await refresh();
    void reload();
    toast.success("Active dataset changed");
  };
  const remove = async (id: number) => {
    if (!window.confirm("Delete this dataset and its investigations? This can't be undone.")) return;
    await api(`/api/data-sources/${id}`, { method: "DELETE" });
    toast.success("Dataset deleted");
    await refresh();
    void reload();
  };

  return (
    <div className="space-y-6">
      <PageHeader title="Data Sources" description="Datasets you can analyse, the approved schema the AI may query, and CSV import." />
      {error && <ErrorState error={error} onRetry={reload} />}
      {loading && !data && <Skeleton className="h-40" />}
      {data && (
        <Panel title="Datasets">
          <ul className="-my-2 divide-y">
            {data.items.map((d) => (
              <li key={d.id} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2 font-medium">
                    {d.name} {d.is_synthetic && <SyntheticBadge />}
                    {d.is_active && <span className="rounded-full bg-accent px-2 py-0.5 text-xs text-accent-foreground">Active</span>}
                  </p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {d.row_count.toLocaleString()} campaign-day rows, {shortDate(d.first_date)} to {shortDate(d.last_date)}. {d.is_public ? "Shared demo dataset." : "Private upload."}
                  </p>
                  <div className="mt-1"><FreshnessIndicator f={d.freshness} /></div>
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button variant="outline" size="sm" onClick={() => setPreviewId(previewId === d.id ? null : d.id)} aria-expanded={previewId === d.id}>Preview</Button>
                  {!d.is_active && <Button size="sm" onClick={() => void activate(d.id)}>Use this dataset</Button>}
                  {!d.is_public && <Button variant="ghost" size="icon-sm" aria-label={`Delete ${d.name}`} onClick={() => void remove(d.id)}><Trash2 /></Button>}
                </div>
              </li>
            ))}
          </ul>
          {previewId && preview.data && (
            <div className="mt-4 grid gap-4 xl:grid-cols-2">
              <div className="overflow-x-auto rounded-md border">
                <table className="w-full text-xs"><thead className="bg-muted"><tr>{["campaign_id", "campaign_name", "platform", "objective", "status"].map((c) => <th key={c} className="px-2 py-1.5 text-left">{c}</th>)}</tr></thead>
                  <tbody>{preview.data.campaigns.map((c) => <tr key={c.campaign_id} className="border-t">{["campaign_id", "campaign_name", "platform", "objective", "status"].map((k) => <td key={k} className="px-2 py-1.5">{c[k]}</td>)}</tr>)}</tbody></table>
              </div>
              <div className="overflow-x-auto rounded-md border">
                <table className="w-full text-xs"><thead className="bg-muted"><tr>{["date", "campaign_id", "spend", "clicks", "conversions", "revenue"].map((c) => <th key={c} className="px-2 py-1.5 text-left">{c}</th>)}</tr></thead>
                  <tbody>{preview.data.recent_rows.map((r, i) => <tr key={i} className="border-t">{["date", "campaign_id", "spend", "clicks", "conversions", "revenue"].map((k) => <td key={k} className="px-2 py-1.5 tabular-nums">{typeof r[k] === "number" ? formatMetric(k, r[k]) : r[k]}</td>)}</tr>)}</tbody></table>
              </div>
            </div>
          )}
        </Panel>
      )}

      <Importer onDone={() => void reload()} />

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel title="Approved schema">
          <p className="mb-3 text-sm text-muted-foreground">Generated SQL may only read these tables and columns. Everything else is rejected before execution.</p>
          {schema.data?.tables.map((t) => (
            <div key={t.name} className="mb-4">
              <h3 className="mb-1 font-mono text-sm">analytics.{t.name}</h3>
              <table className="w-full text-sm"><tbody>
                {t.columns.map((c) => <tr key={c.name} className="border-t align-top"><td className="py-1.5 pr-3 font-mono text-xs">{c.name}</td><td className="py-1.5 pr-3 text-xs text-muted-foreground">{c.type}</td><td className="py-1.5 text-xs">{c.description}</td></tr>)}
              </tbody></table>
            </div>
          ))}
          {schema.data && <p className="text-xs text-muted-foreground">{schema.data.relationships.join("; ")}</p>}
        </Panel>
        <Panel title="Metric definitions">
          <dl className="space-y-3 text-sm">
            {metrics.data?.metrics.map((m) => (
              <div key={m.key}>
                <dt className="font-medium">{m.label} <span className="font-mono text-xs font-normal text-muted-foreground">{m.formula}</span></dt>
                <dd className="text-muted-foreground">{m.definition} {m.zero_handling}</dd>
              </div>
            ))}
          </dl>
        </Panel>
      </div>

      {data && (
        <Panel title="Connectors">
          <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {data.connectors.map((c) => (
              <li key={c.key} className={cn("rounded-md border p-3", c.status === "planned" && "bg-muted/50")}>
                <p className="flex items-center justify-between gap-2 text-sm font-medium">
                  {c.name}
                  <span className={cn("rounded-full px-2 py-0.5 text-xs", c.status === "available" ? "bg-accent text-accent-foreground" : "border text-muted-foreground")}>
                    {c.status === "available" ? "Available" : "Not available yet"}
                  </span>
                </p>
                <p className="mt-1 text-xs text-muted-foreground">{c.description}</p>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </div>
  );
}
