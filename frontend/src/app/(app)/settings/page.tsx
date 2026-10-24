"use client";

import { useMemo, useState } from "react";
import { useTheme } from "next-themes";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { SystemStatus, User } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useSession } from "@/components/session";
import { PageHeader, Panel } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const SENS = [
  { key: "conservative", label: "Conservative", hint: "Only large, clear deviations" },
  { key: "balanced", label: "Balanced", hint: "Default" },
  { key: "sensitive", label: "Sensitive", hint: "More flags, more noise" },
] as const;

export default function SettingsPage() {
  const { user, refresh } = useSession();
  const { theme, setTheme } = useTheme();
  const status = useApi<SystemStatus>("/api/system/status");
  const [name, setName] = useState(user?.display_name ?? "");
  const zones = useMemo(() => {
    try {
      return (Intl as unknown as { supportedValuesOf: (k: string) => string[] }).supportedValuesOf("timeZone");
    } catch {
      return ["UTC"];
    }
  }, []);

  const save = async (body: Partial<User>, msg: string) => {
    try {
      await api("/api/auth/me", { method: "PATCH", body });
      await refresh();
      toast.success(msg);
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  const s = status.data;

  return (
    <div className="space-y-6">
      <PageHeader title="Settings" description="Your preferences and how this workspace is configured." />

      <Panel title="AI model">
        {s && (
          <div className="space-y-3 text-sm">
            <p className="flex items-center gap-2">
              <span className={cn("size-2 rounded-full", s.mode === "llm" ? "bg-good" : "bg-caution")} aria-hidden />
              {s.mode === "llm" ? <>Connected to <b>{s.llm_provider}</b>, model <b>{s.llm_model}</b>.</> : <>Demo mode. No LLM API key is configured, so no LLM is called.</>}
            </p>
            {s.mode === "demo" && (
              <div className="rounded-md border bg-muted/50 p-3">
                <p>In demo mode, questions are interpreted by keyword rules and explained with templates. SQL validation, database execution and every number are real.</p>
                <p className="mt-2">To enable an LLM, set these variables in the backend&apos;s <code className="font-mono text-xs">.env</code> and restart the API. Keys stay on the server and are never sent to the browser.</p>
                <pre className="mt-2 overflow-auto rounded bg-card p-3 font-mono text-xs">{`LLM_PROVIDER=anthropic        # or: openai
LLM_API_KEY=...               # your key
LLM_MODEL=claude-sonnet-4-5   # optional; any model your key can use
# LLM_BASE_URL=...            # optional, OpenAI-compatible gateways`}</pre>
              </div>
            )}
            <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
              <div><dt className="inline text-muted-foreground">Query timeout: </dt><dd className="inline">{s.query_timeout_ms / 1000} s</dd></div>
              <div><dt className="inline text-muted-foreground">Row limit per query: </dt><dd className="inline">{s.query_row_limit.toLocaleString()}</dd></div>
              <div><dt className="inline text-muted-foreground">SQL repair attempts: </dt><dd className="inline">{s.sql_repair_attempts}</dd></div>
              <div><dt className="inline text-muted-foreground">Analyses per minute: </dt><dd className="inline">{s.analysis_rate_limit_per_minute}</dd></div>
              <div><dt className="inline text-muted-foreground">Upload limit: </dt><dd className="inline">{s.upload_max_mb} MB, {s.upload_max_rows.toLocaleString()} rows</dd></div>
              <div><dt className="inline text-muted-foreground">Anomaly detector: </dt><dd className="inline">{s.anomaly_detector}</dd></div>
            </dl>
          </div>
        )}
      </Panel>

      <Panel title="Anomaly sensitivity">
        <div role="radiogroup" aria-label="Anomaly sensitivity" className="grid gap-2 sm:grid-cols-3">
          {SENS.map((o) => (
            <button
              key={o.key}
              type="button"
              role="radio"
              aria-checked={user?.anomaly_sensitivity === o.key}
              onClick={() => void save({ anomaly_sensitivity: o.key }, `Sensitivity set to ${o.label.toLowerCase()}`)}
              className={cn("rounded-md border p-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring", user?.anomaly_sensitivity === o.key ? "border-primary bg-accent/50" : "hover:border-primary/40")}
            >
              <span className="block text-sm font-medium">{o.label}</span>
              <span className="block text-xs text-muted-foreground">{o.hint}. Flags at |z| ≥ {s?.sensitivity_thresholds[o.key] ?? "…"}.</span>
            </button>
          ))}
        </div>
      </Panel>

      <Panel title="Reporting">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <label htmlFor="tz" className="text-xs text-muted-foreground">Reporting timezone</label>
            <select id="tz" value={user?.reporting_timezone} onChange={(e) => void save({ reporting_timezone: e.target.value }, "Timezone updated")} className="h-8 w-64 rounded-md border bg-card px-2 text-sm">
              {zones.map((z) => <option key={z} value={z}>{z}</option>)}
            </select>
          </div>
          <p className="max-w-[60ch] text-xs text-muted-foreground">Used to decide what &ldquo;today&rdquo; is when resolving relative dates and data freshness. Relative ranges never run past the latest date with data.</p>
        </div>
      </Panel>

      <Panel title="Profile and appearance">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <label htmlFor="dn" className="text-xs text-muted-foreground">Display name</label>
            <Input id="dn" value={name} onChange={(e) => setName(e.target.value)} disabled={user?.is_demo} className="w-64" maxLength={60} />
          </div>
          <Button variant="outline" disabled={user?.is_demo || !name.trim() || name === user?.display_name} onClick={() => void save({ display_name: name.trim() }, "Name updated")}>Save name</Button>
          <div role="group" aria-label="Theme" className="ml-auto inline-flex rounded-md border p-0.5">
            {["light", "dark"].map((t) => (
              <button key={t} type="button" aria-pressed={theme === t} onClick={() => setTheme(t)} className={cn("rounded px-3 py-1 text-sm capitalize outline-none focus-visible:ring-2 focus-visible:ring-ring", theme === t ? "bg-secondary font-medium" : "text-muted-foreground")}>
                {t}
              </button>
            ))}
          </div>
        </div>
        {user?.is_demo && <p className="mt-2 text-xs text-muted-foreground">You are using the shared demo account. Its investigations and settings are visible to anyone using the demo.</p>}
      </Panel>
    </div>
  );
}
