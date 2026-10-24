"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "./api";

type State<T> = { key: string | null; data: T | null; error: ApiError | null };

/** Fetch JSON from the API. Keeps the previous data while a new request is in flight. */
export function useApi<T>(path: string | null) {
  const [nonce, setNonce] = useState(0);
  const [state, setState] = useState<State<T>>({ key: null, data: null, error: null });
  const key = path ? `${path}#${nonce}` : null;

  useEffect(() => {
    if (!path || !key) return;
    let alive = true;
    api<T>(path).then(
      (data) => alive && setState({ key, data, error: null }),
      (e) =>
        alive &&
        setState((s) => ({ key, data: s.data, error: e instanceof ApiError ? e : new ApiError(0, "unknown", String(e)) })),
    );
    return () => {
      alive = false;
    };
  }, [path, key]);

  const reload = useCallback(async () => setNonce((n) => n + 1), []);
  const setData = useCallback(
    (fn: T | null | ((d: T | null) => T | null)) =>
      setState((s) => ({ ...s, data: typeof fn === "function" ? (fn as (d: T | null) => T | null)(s.data) : fn })),
    [],
  );
  return { data: state.data, error: state.error, loading: key !== null && state.key !== key, reload, setData };
}
