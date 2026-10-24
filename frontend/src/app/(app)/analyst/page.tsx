"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { Info, Loader2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Analysis, SystemStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { AskBar } from "@/components/ask-bar";
import { ErrorState, PageHeader, StatusPill } from "@/components/common";
import { InvestigationView } from "@/components/investigation-view";
import { Skeleton } from "@/components/ui/skeleton";

function Running({ question }: { question: string }) {
  return (
    <div className="space-y-4" aria-live="polite" aria-busy="true">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" /> Analysing “{question}”. Interpreting, validating SQL, querying and checking the
        numbers usually takes a few seconds.
      </div>
      <Skeleton className="h-28 w-full" />
      <Skeleton className="h-56 w-full" />
      <div className="grid gap-5 lg:grid-cols-2"><Skeleton className="h-36" /><Skeleton className="h-36" /></div>
    </div>
  );
}

function AnalystInner() {
  const params = useSearchParams();
  const router = useRouter();
  const status = useApi<SystemStatus>("/api/system/status");
  const [current, setCurrent] = useState<Analysis | null>(null);
  const [thread, setThread] = useState<Analysis[]>([]);
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [draft, setDraft] = useState("");
  const started = useRef<string | null>(null);

  const remember = useCallback((a: Analysis) => {
    setCurrent(a);
    setThread((t) => [a, ...t.filter((x) => x.id !== a.id)].slice(0, 12));
  }, []);

  const run = useCallback(async (question: string, parentId?: number) => {
    setRunning(question);
    setError(null);
    try {
      const a = await api<Analysis>("/api/analyses", { body: { question, parent_id: parentId } });
      remember(a);
      router.replace(`/analyst?id=${a.id}`, { scroll: false });
      if (a.status === "succeeded") toast.success("Analysis complete");
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setRunning(null);
    }
  }, [remember, router]);

  const rerun = useCallback(async (a: Analysis) => {
    setRunning(a.question);
    setError(null);
    try {
      const n = await api<Analysis>(`/api/analyses/${a.id}/retry`, { method: "POST" });
      remember(n);
      router.replace(`/analyst?id=${n.id}`, { scroll: false });
      toast.success("Re-ran on current data");
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setRunning(null);
    }
  }, [remember, router]);

  useEffect(() => {
    const q = params.get("q");
    const id = params.get("id");
    if (q && started.current !== q) {
      started.current = q;
      void run(q);
    } else if (id && !q && current?.id !== Number(id)) {
      api<Analysis>(`/api/analyses/${id}`).then(remember).catch((e) => setError(e as ApiError));
    }
  }, [params, run, remember, current?.id]);

  const demo = status.data?.mode === "demo";

  return (
    <div>
      <PageHeader
        title="AI Analyst"
        description="Ask a question in plain English. Each answer shows the validated SQL, the query result, deterministic calculations and what the evidence does not tell you."
      />
      {demo && (
        <p className="mb-4 flex items-start gap-2 rounded-md border bg-card px-3 py-2 text-sm text-muted-foreground">
          <Info className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
          <span>
            Demo mode: no LLM is configured, so questions are interpreted by rules and narrated from templates. SQL
            validation, execution and all numbers are real. <Link href="/settings" className="text-primary underline-offset-4 hover:underline">Configure an LLM</Link>
          </span>
        </p>
      )}
      <div className="grid gap-8 xl:grid-cols-[1fr_240px]">
        <div className="min-w-0 space-y-6">
          <AskBar onAsk={(q) => void run(q, current?.id && draft === current.question ? current.id : undefined)} busy={!!running} initial={draft} showExamples={!current && !running} />
          {error && <ErrorState error={error} onRetry={() => setError(null)} />}
          {running ? (
            <Running question={running} />
          ) : current ? (
            <InvestigationView
              a={current}
              onChange={remember}
              onRerun={() => void rerun(current)}
              onRefine={(q) => {
                setDraft(q);
                window.scrollTo({ top: 0, behavior: "smooth" });
                setTimeout(() => document.getElementById("ask")?.focus(), 250);
              }}
            />
          ) : (
            !error && (
              <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
                Pick an example above or type your own question. Answers are grounded in the{" "}
                <Link href="/data-sources" className="text-primary underline-offset-4 hover:underline">approved schema</Link>.
              </div>
            )
          )}
        </div>
        <aside className="hidden xl:block" aria-label="This session">
          <h2 className="mb-2 text-sm font-semibold">This session</h2>
          {thread.length === 0 ? (
            <p className="text-sm text-muted-foreground">Questions you ask here will be listed for quick switching.</p>
          ) : (
            <ul className="space-y-1">
              {thread.map((t) => (
                <li key={t.id}>
                  <button
                    type="button"
                    onClick={() => { setCurrent(t); router.replace(`/analyst?id=${t.id}`, { scroll: false }); }}
                    className={cn("w-full rounded-md px-2 py-2 text-left text-sm outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring", current?.id === t.id && "bg-muted")}
                  >
                    <span className="line-clamp-2">{t.question}</span>
                    <span className="mt-1 block"><StatusPill status={t.status} /></span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <Link href="/history" className="mt-3 inline-block text-sm text-primary underline-offset-4 hover:underline">All investigations</Link>
        </aside>
      </div>
    </div>
  );
}

export default function AnalystPage() {
  return (
    <Suspense fallback={<Skeleton className="h-40 w-full" />}>
      <AnalystInner />
    </Suspense>
  );
}
