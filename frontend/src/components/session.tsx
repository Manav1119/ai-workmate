"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { User } from "@/lib/types";

type Session = { user: User | null; loading: boolean; refresh: () => Promise<void>; signOut: () => Promise<void> };

const Ctx = createContext<Session>({ user: null, loading: true, refresh: async () => {}, signOut: async () => {} });

export function SessionProvider({ children, requireAuth = true }: { children: React.ReactNode; requireAuth?: boolean }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  const load = useCallback(
    () =>
      api<User>("/api/auth/me").then(
        (u) => {
          setUser(u);
          setLoading(false);
        },
        (e) => {
          setUser(null);
          setLoading(false);
          if (requireAuth && e instanceof ApiError && e.status === 401) router.replace("/login");
        },
      ),
    [requireAuth, router],
  );
  const refresh = useCallback(async () => {
    await load();
  }, [load]);

  const signOut = useCallback(async () => {
    await api("/api/auth/logout", { method: "POST" });
    setUser(null);
    router.replace("/login");
  }, [router]);

  useEffect(() => {
    void load();
  }, [load]);

  return <Ctx.Provider value={{ user, loading, refresh, signOut }}>{children}</Ctx.Provider>;
}

export const useSession = () => useContext(Ctx);
