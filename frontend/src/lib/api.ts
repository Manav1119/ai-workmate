// Thin client for the FastAPI backend. All calls are same-origin (proxied by Next.js),
// authenticated by an httpOnly session cookie, and carry the anti-CSRF header.

export class ApiError extends Error {
  status: number;
  code: string;
  details?: unknown;
  requestId?: string;
  constructor(status: number, code: string, message: string, details?: unknown, requestId?: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

type Opts = { method?: string; body?: unknown; form?: FormData; signal?: AbortSignal };

export async function api<T>(path: string, opts: Opts = {}): Promise<T> {
  const headers: Record<string, string> = { "X-Requested-With": "aiworkmate" };
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(path, {
      method: opts.method ?? (body ? "POST" : "GET"),
      headers,
      body,
      credentials: "same-origin",
      signal: opts.signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "network_error", "Can't reach the AI Workmate server. Check that the backend is running.");
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const err = (data as { error?: { code: string; message: string; details?: unknown; request_id?: string } })?.error;
    throw new ApiError(
      res.status,
      err?.code ?? "http_error",
      err?.message ?? `Request failed (HTTP ${res.status}).`,
      err?.details,
      err?.request_id,
    );
  }
  return data as T;
}

export async function download(path: string, fallbackName: string): Promise<void> {
  const res = await fetch(path, { credentials: "same-origin" });
  if (!res.ok) throw new ApiError(res.status, "download_failed", "The export could not be generated.");
  const blob = await res.blob();
  const cd = res.headers.get("content-disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(cd)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
