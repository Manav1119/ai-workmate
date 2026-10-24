"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { BookmarkCheck, RefreshCw, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Analysis, AnalysisSummary, Page } from "@/lib/types";
import { dateTime } from "@/lib/format";
import { EmptyState, ErrorState, ModePill, PageHeader, StatusPill } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";

const PAGE = 20;

export default function HistoryPage() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [status, setStatus] = useState("");
  const [saved, setSaved] = useState(false);
  const [offset, setOffset] = useState(0);
  useEffect(() => {
    const t = setTimeout(() => { setDebounced(q); setOffset(0); }, 250);
    return () => clearTimeout(t);
  }, [q]);
  const qs = useMemo(() => {
    const p = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
    if (debounced) p.set("q", debounced);
    if (status) p.set("status", status);
    if (saved) p.set("saved", "true");
    return p.toString();
  }, [debounced, status, saved, offset]);
  const { data, error, loading, reload } = useApi<Page<AnalysisSummary>>(`/api/analyses?${qs}`);

  const retry = async (id: number) => {
    try {
      const a = await api<Analysis>(`/api/analyses/${id}/retry`, { method: "POST" });
      toast.success("Re-ran the investigation");
      router.push(`/analyst?id=${a.id}`);
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  const remove = async (id: number) => {
    if (!window.confirm("Delete this investigation? Saved reports made from it are kept.")) return;
    await api(`/api/analyses/${id}`, { method: "DELETE" });
    toast.success("Investigation deleted");
    void reload();
  };

  return (
    <div>
      <PageHeader title="Investigation History" description="Every question you ask is stored with its SQL, result, explanation and limitations. Reopen to view the stored result, or re-run against current data." />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="min-w-[240px] flex-1">
          <label htmlFor="search" className="sr-only">Search investigations</label>
          <Input id="search" placeholder="Search questions" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <label className="sr-only" htmlFor="status">Status</label>
        <select id="status" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }} className="h-8 rounded-md border bg-card px-2 text-sm">
          <option value="">All statuses</option>
          <option value="succeeded">Answered</option>
          <option value="failed">Failed</option>
          <option value="needs_clarification">Needs clarification</option>
          <option value="unsupported">Not answerable</option>
          <option value="rejected">Rejected</option>
        </select>
        <label className="flex h-8 items-center gap-2 text-sm">
          <input type="checkbox" checked={saved} onChange={(e) => { setSaved(e.target.checked); setOffset(0); }} className="size-4 accent-[var(--primary)]" />
          Saved only
        </label>
      </div>
      {error && <ErrorState error={error} onRetry={reload} />}
      {loading && !data && <Skeleton className="h-80 w-full" />}
      {data && data.items.length === 0 && (
        <EmptyState title={debounced || status || saved ? "No investigations match" : "No investigations yet"} action={<Button render={<Link href="/analyst" />}>Ask a question</Button>}>
          {debounced || status || saved ? "Try a different search or filter." : "Questions you ask in the AI Analyst are saved here automatically."}
        </EmptyState>
      )}
      {data && data.items.length > 0 && (
        <>
          <ul className="divide-y rounded-lg border bg-card" data-testid="history-list">
            {data.items.map((a) => (
              <li key={a.id} className="flex flex-col gap-2 p-4 sm:flex-row sm:items-start sm:justify-between">
                <Link href={`/analyst?id=${a.id}`} className="min-w-0 flex-1 rounded outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  <p className="flex items-center gap-2 font-medium hover:text-primary">
                    {a.saved && <BookmarkCheck className="size-4 shrink-0 text-primary" aria-label="Saved" />}
                    <span className="truncate">{a.title && a.title !== a.question ? a.title : a.question}</span>
                  </p>
                  <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{a.summary ?? a.error_message ?? ""}</p>
                  <p className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <StatusPill status={a.status} /> <ModePill mode={a.mode} /> {dateTime(a.created_at)}
                    {a.duration_ms !== null && <span>{(a.duration_ms / 1000).toFixed(2)} s</span>}
                    {a.parent_id && <span>Re-run of #{a.parent_id}</span>}
                  </p>
                </Link>
                <div className="flex shrink-0 gap-1">
                  <Button variant="outline" size="sm" onClick={() => void retry(a.id)}>
                    <RefreshCw /> {a.status === "succeeded" ? "Re-run" : "Retry"}
                  </Button>
                  <Button variant="ghost" size="icon-sm" aria-label="Delete investigation" onClick={() => void remove(a.id)}>
                    <Trash2 />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
          <div className="mt-3 flex items-center justify-between text-sm text-muted-foreground">
            <span>{offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total}</span>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" disabled={offset === 0} onClick={() => setOffset(offset - PAGE)}>Previous</Button>
              <Button variant="outline" size="sm" disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>Next</Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
