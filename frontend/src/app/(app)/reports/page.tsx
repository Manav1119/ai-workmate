"use client";

import { useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { Copy, Download, Loader2, Newspaper, Trash2 } from "lucide-react";
import { api, download } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Page, Report } from "@/lib/types";
import { dateTime, shortDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, PageHeader } from "@/components/common";
import { Markdown } from "@/components/markdown";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

type Briefing = { markdown: string; anchor_date: string; new_anomalies: number };

export default function ReportsPage() {
  const list = useApi<Page<Report>>("/api/reports?limit=50");
  const [selected, setSelected] = useState<Report | null>(null);
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [busy, setBusy] = useState(false);

  const open = async (id: number) => {
    setBriefing(null);
    setSelected(await api<Report>(`/api/reports/${id}`));
  };
  const generate = async () => {
    setBusy(true);
    try {
      setSelected(null);
      setBriefing(await api<Briefing>("/api/briefings", { method: "POST" }));
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const saveBriefing = async () => {
    const r = await api<Report>("/api/reports", { body: { kind: "briefing" } });
    toast.success("Briefing saved");
    await list.reload();
    setBriefing(null);
    setSelected(r);
  };
  const remove = async (id: number) => {
    if (!window.confirm("Delete this report?")) return;
    await api(`/api/reports/${id}`, { method: "DELETE" });
    setSelected(null);
    toast.success("Report deleted");
    void list.reload();
  };

  const doc = selected?.markdown ?? briefing?.markdown;

  return (
    <div>
      <PageHeader
        title="Reports"
        description="Saved investigation reports and daily briefings. Reports are snapshots: they keep the numbers from when they were made."
        actions={
          <Button onClick={() => void generate()} disabled={busy}>
            {busy ? <Loader2 className="animate-spin" /> : <Newspaper />} Generate briefing
          </Button>
        }
      />
      <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
        <div>
          {list.error && <ErrorState error={list.error} onRetry={list.reload} />}
          {list.loading && !list.data && <Skeleton className="h-60" />}
          {list.data && list.data.items.length === 0 && (
            <EmptyState title="No saved reports">
              Save one from an investigation (&ldquo;Save as report&rdquo;) or generate a daily briefing.
            </EmptyState>
          )}
          {list.data && list.data.items.length > 0 && (
            <ul className="space-y-1" aria-label="Saved reports">
              {list.data.items.map((r) => (
                <li key={r.id}>
                  <button
                    type="button"
                    onClick={() => void open(r.id)}
                    className={cn("w-full rounded-md border bg-card px-3 py-2.5 text-left outline-none hover:border-primary/40 focus-visible:ring-2 focus-visible:ring-ring", selected?.id === r.id && "border-primary/60")}
                  >
                    <span className="block truncate text-sm font-medium">{r.title}</span>
                    <span className="mt-0.5 block text-xs text-muted-foreground">
                      {r.kind === "briefing" ? "Briefing" : "Investigation"}, saved {dateTime(r.created_at)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="min-w-0">
          {!doc && <EmptyState title="Select a report to read it">Or generate today&apos;s briefing to see what changed.</EmptyState>}
          {doc && (
            <article className="rounded-lg border bg-card">
              <div className="flex flex-wrap items-center gap-2 border-b px-4 py-3">
                <span className="mr-auto text-xs text-muted-foreground">
                  {selected ? `Snapshot with data through ${shortDate(selected.data_as_of)}` : "Unsaved briefing, generated just now without an LLM"}
                </span>
                {briefing && <Button size="sm" onClick={() => void saveBriefing()}>Save briefing</Button>}
                {selected && (
                  <>
                    <Button variant="outline" size="sm" onClick={() => void download(`/api/reports/${selected.id}/export?format=markdown`, `report-${selected.id}.md`)}><Download /> Markdown</Button>
                    <Button variant="outline" size="sm" onClick={() => void download(`/api/reports/${selected.id}/export?format=pdf`, `report-${selected.id}.pdf`)}><Download /> PDF</Button>
                  </>
                )}
                <Button variant="ghost" size="sm" onClick={() => { void navigator.clipboard.writeText(doc); toast.success("Copied as Markdown"); }}><Copy /> Copy</Button>
                {selected?.analysis_id && <Button variant="ghost" size="sm" render={<Link href={`/analyst?id=${selected.analysis_id}`} />}>Open investigation</Button>}
                {selected && <Button variant="ghost" size="icon-sm" aria-label="Delete report" onClick={() => void remove(selected.id)}><Trash2 /></Button>}
              </div>
              <div className="max-w-[78ch] p-5" data-testid="report-body"><Markdown source={doc} /></div>
            </article>
          )}
        </div>
      </div>
    </div>
  );
}
