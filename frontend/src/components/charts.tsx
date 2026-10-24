"use client";

import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { formatMetric, shortDate } from "@/lib/format";
import type { ChartSpec } from "@/lib/types";

const PALETTE = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)"];

const axis = { fontSize: 12, fill: "var(--muted-foreground)" };

function TooltipBox({ active, payload, label, unitOf, isDate }: {
  active?: boolean; payload?: Array<{ name: string; value: number; color: string; dataKey: string }>; label?: string;
  unitOf: (k: string) => string | null; isDate: boolean;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border bg-popover px-3 py-2 text-xs shadow-sm">
      <p className="mb-1 font-medium">{isDate ? shortDate(String(label)) : label}</p>
      {payload.map((p) => (
        <p key={p.dataKey} className="flex items-center gap-2 tabular-nums">
          <span className="size-2 rounded-full" style={{ background: p.color }} aria-hidden />
          {p.name}: {formatMetric(unitOf(p.dataKey), p.value)}
        </p>
      ))}
    </div>
  );
}

export function ChartView({ spec, height = 280 }: { spec: ChartSpec; height?: number }) {
  const isDate = spec.x_key === "date";
  const unitOf = (k: string) => spec.series.find((s) => s.key === k)?.unit_metric ?? spec.unit_metric;
  const tick = (v: unknown) => (isDate ? shortDate(String(v)) : String(v).length > 16 ? `${String(v).slice(0, 15)}…` : String(v));
  const dual = spec.type === "line" && spec.series.length > 1 && spec.series[0].unit_metric !== spec.series[1].unit_metric;
  const summary = `${spec.title}. ${spec.data.length} data points.`;

  if (spec.type === "line") {
    return (
      <figure aria-label={summary}>
        <figcaption className="mb-2 text-sm font-medium">{spec.title}</figcaption>
        <ResponsiveContainer width="100%" height={height}>
          <LineChart data={spec.data} margin={{ top: 8, right: dual ? 8 : 16, left: 4, bottom: 0 }}>
            <CartesianGrid stroke="var(--border)" vertical={false} />
            <XAxis dataKey={spec.x_key} tickFormatter={tick} tick={axis} tickLine={false} axisLine={false} minTickGap={24} />
            <YAxis yAxisId="a" tick={axis} tickLine={false} axisLine={false} width={64} tickFormatter={(v) => formatMetric(spec.series[0].unit_metric ?? spec.unit_metric, v, { compact: true })} />
            {dual && <YAxis yAxisId="b" orientation="right" tick={axis} tickLine={false} axisLine={false} width={64} tickFormatter={(v) => formatMetric(spec.series[1].unit_metric, v, { compact: true })} />}
            <Tooltip content={<TooltipBox unitOf={unitOf} isDate={isDate} />} />
            {spec.series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
            {spec.series.map((s, i) => (
              <Line key={s.key} yAxisId={dual && i === 1 ? "b" : "a"} type="monotone" dataKey={s.key} name={s.label} stroke={PALETTE[i]} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </figure>
    );
  }

  const horizontal = spec.data.length > 6 || spec.type === "bar";
  return (
    <figure aria-label={summary}>
      <figcaption className="mb-2 text-sm font-medium">{spec.title}</figcaption>
      <ResponsiveContainer width="100%" height={horizontal ? Math.max(160, spec.data.length * 34 + 40) : height}>
        <BarChart data={spec.data} layout={horizontal ? "vertical" : "horizontal"} margin={{ top: 4, right: 16, left: 4, bottom: 0 }}>
          <CartesianGrid stroke="var(--border)" horizontal={!horizontal} vertical={horizontal} />
          {horizontal ? (
            <>
              <XAxis type="number" tick={axis} tickLine={false} axisLine={false} tickFormatter={(v) => formatMetric(spec.unit_metric, v, { compact: true })} />
              <YAxis type="category" dataKey={spec.x_key} tick={axis} tickLine={false} axisLine={false} width={170} tickFormatter={(v) => (String(v).length > 24 ? `${String(v).slice(0, 23)}…` : String(v))} />
            </>
          ) : (
            <>
              <XAxis dataKey={spec.x_key} tick={axis} tickLine={false} axisLine={false} tickFormatter={tick} />
              <YAxis tick={axis} tickLine={false} axisLine={false} width={64} tickFormatter={(v) => formatMetric(spec.unit_metric, v, { compact: true })} />
            </>
          )}
          <Tooltip cursor={{ fill: "var(--muted)" }} content={<TooltipBox unitOf={unitOf} isDate={isDate} />} />
          {spec.series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
          {spec.diverging && <ReferenceLine {...(horizontal ? { x: 0 } : { y: 0 })} stroke="var(--muted-foreground)" />}
          {spec.series.map((s, i) => (
            <Bar key={s.key} dataKey={s.key} name={s.label} fill={spec.type === "grouped_bar" && spec.series.length === 2 ? (i === 0 ? "var(--chart-2)" : "var(--chart-1)") : PALETTE[i]} radius={2} isAnimationActive={false} maxBarSize={28}>
              {(spec.diverging || spec.highlight_key) &&
                spec.data.map((d, j) => {
                  const v = Number(d[s.key]);
                  let fill = PALETTE[i];
                  if (spec.diverging) fill = v < 0 ? "var(--bad)" : "var(--good)";
                  if (spec.highlight_key) fill = d[spec.highlight_key] ? "var(--bad)" : "var(--chart-2)";
                  return <Cell key={j} fill={fill} />;
                })}
            </Bar>
          ))}
        </BarChart>
      </ResponsiveContainer>
      {spec.diverging && <p className="mt-1 text-xs text-muted-foreground">Bars show each segment&apos;s contribution to the total change; they sum to the net change.</p>}
      {spec.highlight_key && <p className="mt-1 text-xs text-muted-foreground">Red bars meet the highlight rule shown below.</p>}
    </figure>
  );
}
