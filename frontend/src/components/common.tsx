"use client";

import { AlertTriangle, Inbox, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import type { Freshness } from "@/lib/types";
import { shortDate, STATUS_LABEL } from "@/lib/format";
import type { ApiError } from "@/lib/api";

export function PageHeader({ title, description, actions }: { title: string; description?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold">{title}</h1>
        {description && <p className="mt-1 max-w-[70ch] text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Panel({ title, action, children, className }: { title?: React.ReactNode; action?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-lg border bg-card", className)}>
      {(title || action) && (
        <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
          {typeof title === "string" ? <h2 className="text-sm font-semibold">{title}</h2> : title}
          {action}
        </div>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-6 py-10 text-center">
      <Inbox className="size-5 text-muted-foreground" aria-hidden />
      <p className="text-sm font-medium">{title}</p>
      {children && <p className="max-w-[52ch] text-sm text-muted-foreground">{children}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: ApiError | Error; onRetry?: () => void }) {
  const rid = (error as ApiError).requestId;
  return (
    <div role="alert" className="flex flex-col items-start gap-2 rounded-lg border border-bad/30 bg-bad/5 p-4">
      <div className="flex items-center gap-2 text-sm font-medium text-bad">
        <AlertTriangle className="size-4" aria-hidden /> {error.message}
      </div>
      {rid && <p className="text-xs text-muted-foreground">Request ID {rid}</p>}
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw /> Try again
        </Button>
      )}
    </div>
  );
}

export function FreshnessIndicator({ f }: { f: Freshness }) {
  const tone = f.status === "fresh" ? "bg-good" : f.status === "stale" ? "bg-caution" : "bg-bad";
  const age =
    f.days_since_last_data === null ? "" : f.days_since_last_data === 0 ? "updated today" : `${f.days_since_last_data} day${f.days_since_last_data === 1 ? "" : "s"} old`;
  return (
    <span className="inline-flex items-center gap-2 text-sm text-muted-foreground" title={`Reporting timezone ${f.reporting_timezone}`}>
      <span className={cn("size-2 rounded-full", tone)} aria-hidden />
      Data through {shortDate(f.last_data_date)}
      {age && <span>({age})</span>}
    </span>
  );
}

export function SyntheticBadge() {
  return (
    <span className="inline-flex items-center rounded border border-caution/40 bg-caution/10 px-1.5 py-0.5 text-xs font-medium text-caution">
      Synthetic data
    </span>
  );
}

const STATUS_TONE: Record<string, string> = {
  succeeded: "border-good/30 bg-good/10 text-good",
  failed: "border-bad/30 bg-bad/10 text-bad",
  rejected: "border-bad/30 bg-bad/10 text-bad",
  needs_clarification: "border-caution/40 bg-caution/10 text-caution",
  unsupported: "border-border bg-muted text-muted-foreground",
  running: "border-border bg-muted text-muted-foreground",
};

export function StatusPill({ status }: { status: string }) {
  return (
    <span className={cn("inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-xs font-medium", STATUS_TONE[status])}>
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

export function ModePill({ mode }: { mode: "llm" | "demo" }) {
  return mode === "llm" ? (
    <span className="inline-flex items-center rounded-full border border-primary/30 bg-accent px-2 py-0.5 text-xs font-medium text-accent-foreground">
      LLM
    </span>
  ) : (
    <span
      className="inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium text-muted-foreground"
      title="Rule-based interpretation and template narrative. No LLM was called."
    >
      Demo mode
    </span>
  );
}

const SEV: Record<string, string> = {
  high: "bg-bad/10 text-bad border-bad/30",
  medium: "bg-caution/10 text-caution border-caution/40",
  low: "bg-muted text-muted-foreground border-border",
};

export function SeverityPill({ severity }: { severity: string }) {
  return <span className={cn("inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium capitalize", SEV[severity])}>{severity}</span>;
}

export function Delta({ display, tone }: { display: string; tone: "good" | "bad" | "neutral" }) {
  return (
    <span className={cn("font-medium tabular-nums", tone === "good" && "text-good", tone === "bad" && "text-bad", tone === "neutral" && "text-muted-foreground")}>
      {display}
    </span>
  );
}
