"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"signin" | "register">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (kind: string, fn: () => Promise<unknown>) => {
    setBusy(kind);
    setError(null);
    try {
      await fn();
      router.replace("/");
    } catch (e) {
      const err = e as ApiError;
      const detail = Array.isArray(err.details) ? (err.details as Array<{ msg: string }>).map((d) => d.msg).join("; ") : "";
      setError(detail ? `${err.message} ${detail}` : err.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <main className="grid min-h-screen bg-background lg:grid-cols-[1fr_minmax(420px,520px)]">
      <section className="hidden flex-col justify-between border-r bg-card p-12 lg:flex">
        <div className="flex items-center gap-2 text-[15px] font-semibold">
          <svg viewBox="0 0 24 24" className="size-6" aria-hidden>
            <rect x="2" y="11" width="4" height="10" rx="1" className="fill-muted-foreground/40" />
            <rect x="9" y="6" width="4" height="15" rx="1" className="fill-muted-foreground/60" />
            <rect x="16" y="3" width="4" height="18" rx="1" className="fill-primary" />
          </svg>
          AI Workmate
        </div>
        <div className="max-w-[46ch]">
          <h1 className="text-3xl font-semibold leading-tight">From raw data to clear answers and better decisions.</h1>
          <p className="mt-4 text-[15px] leading-7 text-muted-foreground">
            Ask why a metric moved. AI Workmate writes the SQL, validates it before it touches the database, computes the
            numbers deterministically and explains only what the evidence supports.
          </p>
          <p className="mt-6 text-[15px] leading-8">
            Conversions fell{" "}
            <span className="rounded-[3px] bg-fact px-1 font-medium text-fact-foreground">−3.1%</span> last week; the
            largest contributor was Prospecting - Lookalike{" "}
            <span className="rounded-[3px] bg-fact px-1 font-medium text-fact-foreground">−462</span>.
          </p>
          <p className="mt-1 text-xs text-muted-foreground">Every highlighted number traces back to a query result.</p>
        </div>
        <p className="text-xs text-muted-foreground">The demo workspace uses synthetic data only.</p>
      </section>

      <section className="flex items-center justify-center p-6">
        <div className="w-full max-w-sm">
          <h2 className="text-xl font-semibold">{mode === "signin" ? "Sign in" : "Create an account"}</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Or explore the shared demo workspace without an account.
          </p>
          <Button
            className="mt-5 w-full"
            size="lg"
            onClick={() => void run("demo", () => api("/api/auth/demo", { method: "POST" }))}
            disabled={!!busy}
          >
            {busy === "demo" && <Loader2 className="animate-spin" />} Continue with demo account
          </Button>
          <div className="my-6 flex items-center gap-3 text-xs text-muted-foreground">
            <span className="h-px flex-1 bg-border" /> or with email <span className="h-px flex-1 bg-border" />
          </div>
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              void run(mode, () =>
                api(mode === "signin" ? "/api/auth/login" : "/api/auth/register", {
                  body: mode === "signin" ? { email, password } : { email, password, display_name: name },
                }),
              );
            }}
          >
            {mode === "register" && (
              <div className="space-y-1.5">
                <Label htmlFor="name">Name</Label>
                <Input id="name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={60} autoComplete="name" />
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
                minLength={mode === "register" ? 10 : 1} autoComplete={mode === "signin" ? "current-password" : "new-password"}
              />
              {mode === "register" && <p className="text-xs text-muted-foreground">At least 10 characters.</p>}
            </div>
            {error && <p role="alert" className="text-sm text-bad">{error}</p>}
            <Button type="submit" variant="outline" className="w-full" size="lg" disabled={!!busy}>
              {busy === mode && <Loader2 className="animate-spin" />} {mode === "signin" ? "Sign in" : "Create account"}
            </Button>
          </form>
          <button
            type="button"
            className="mt-4 text-sm text-primary underline-offset-4 hover:underline"
            onClick={() => { setMode(mode === "signin" ? "register" : "signin"); setError(null); }}
          >
            {mode === "signin" ? "New here? Create an account" : "Already have an account? Sign in"}
          </button>
        </div>
      </section>
    </main>
  );
}
