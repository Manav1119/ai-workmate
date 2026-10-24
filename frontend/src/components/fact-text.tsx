"use client";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Part } from "@/lib/types";

/**
 * Renders explanation text. Every number the explanation states is a "fact chip": a value
 * substituted from a deterministically computed fact. Hover or focus shows its source.
 */
export function FactText({ parts, text }: { parts?: Part[]; text: string }) {
  if (!parts?.length) return <>{text}</>;
  return (
    <>
      {parts.map((p, i) =>
        p.type === "fact" ? (
          <Tooltip key={i}>
            <TooltipTrigger
              render={
                <span
                  tabIndex={0}
                  data-fact-id={p.fact_id}
                  className="inline-block rounded-[3px] bg-fact px-1 font-medium tabular-nums text-fact-foreground underline decoration-fact-foreground/30 decoration-dotted underline-offset-[3px] outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
              }
            >
              {p.value}
            </TooltipTrigger>
            <TooltipContent className="max-w-xs">
              <span className="block font-medium">{p.label}</span>
              <span className="block opacity-80">Computed from the query result ({p.fact_id})</span>
            </TooltipContent>
          </Tooltip>
        ) : (
          <span key={i}>{p.value}</span>
        ),
      )}
    </>
  );
}
