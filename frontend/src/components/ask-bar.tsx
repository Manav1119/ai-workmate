"use client";

import { useRef, useState } from "react";
import { ArrowUp, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export const EXAMPLES = [
  "Why did conversions fall last week?",
  "Which campaigns contributed most to the increase in CPA?",
  "Compare this week with the previous week",
  "Which campaigns have high spend but low conversion rates?",
  "Show the daily ROAS trend for the last 30 days",
  "Are there any unusual changes in campaign performance?",
  "Which campaigns contributed most to the revenue decline?",
];

export function AskBar({
  onAsk, busy, initial = "", autoFocus, showExamples = true, compact,
}: { onAsk: (q: string) => void; busy?: boolean; initial?: string; autoFocus?: boolean; showExamples?: boolean; compact?: boolean }) {
  const [q, setQ] = useState(initial);
  const [prevInitial, setPrevInitial] = useState(initial);
  const ref = useRef<HTMLTextAreaElement>(null);
  if (initial !== prevInitial) {
    // a new prefilled question (e.g. "Refine question") replaces the draft
    setPrevInitial(initial);
    setQ(initial);
  }
  const submit = () => {
    const v = q.trim();
    if (v.length >= 3 && !busy) onAsk(v);
  };
  return (
    <div>
      <form
        className={cn(
          "flex items-end gap-2 rounded-lg border bg-card p-2 shadow-[0_1px_0_var(--border)] focus-within:border-primary/60 focus-within:ring-3 focus-within:ring-ring/15",
          compact ? "" : "sm:p-3",
        )}
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <label htmlFor="ask" className="sr-only">Ask a question about your data</label>
        <textarea
          id="ask"
          ref={ref}
          autoFocus={autoFocus}
          rows={compact ? 1 : 2}
          maxLength={500}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="Ask about spend, conversions, CPA, ROAS… e.g. Why did conversions fall last week?"
          className="min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-[15px] leading-6 outline-none placeholder:text-muted-foreground"
        />
        <Button type="submit" size="icon-lg" aria-label="Run analysis" disabled={busy || q.trim().length < 3}>
          {busy ? <Loader2 className="animate-spin" /> : <ArrowUp />}
        </Button>
      </form>
      {showExamples && (
        <div className="mt-3 flex flex-wrap gap-2" aria-label="Example questions">
          {EXAMPLES.slice(0, compact ? 4 : 7).map((ex) => (
            <button
              key={ex}
              type="button"
              disabled={busy}
              onClick={() => {
                setQ(ex);
                onAsk(ex);
              }}
              className="rounded-full border bg-card px-3 py-1 text-left text-[13px] text-muted-foreground outline-none transition-colors hover:border-primary/40 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
            >
              {ex}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
