"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useTheme } from "next-themes";
import {
  Activity, Database, FileText, History, LayoutDashboard, LogOut, Menu, Moon, ScanSearch, Settings, Sun,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useSession } from "@/components/session";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";

const NAV = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/analyst", label: "AI Analyst", icon: ScanSearch },
  { href: "/anomalies", label: "Anomaly Monitor", icon: Activity },
  { href: "/history", label: "Investigation History", icon: History },
  { href: "/reports", label: "Reports", icon: FileText },
  { href: "/data-sources", label: "Data Sources", icon: Database },
  { href: "/settings", label: "Settings", icon: Settings },
];

function Mark() {
  // Logo: a small bar chart whose last bar is marked as verified evidence.
  return (
    <svg viewBox="0 0 24 24" className="size-6" aria-hidden>
      <rect x="2" y="11" width="4" height="10" rx="1" className="fill-muted-foreground/40" />
      <rect x="9" y="6" width="4" height="15" rx="1" className="fill-muted-foreground/60" />
      <rect x="16" y="3" width="4" height="18" rx="1" className="fill-primary" />
    </svg>
  );
}

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  const path = usePathname();
  return (
    <nav aria-label="Main" className="flex flex-col gap-0.5">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = href === "/" ? path === "/" : path.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-sidebar-foreground/80 outline-none transition-colors",
              "hover:bg-sidebar-accent hover:text-sidebar-foreground focus-visible:ring-2 focus-visible:ring-ring",
              active && "bg-sidebar-accent font-medium text-sidebar-foreground",
            )}
          >
            <Icon className={cn("size-4", active ? "text-primary" : "text-muted-foreground")} />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

function Footer() {
  const { user, signOut } = useSession();
  const { theme, setTheme } = useTheme();
  return (
    <div className="mt-auto flex items-center gap-2 border-t border-sidebar-border pt-3">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{user?.display_name ?? " "}</p>
        <p className="truncate text-xs text-muted-foreground">{user?.is_demo ? "Shared demo account" : user?.email}</p>
      </div>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
        onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
      >
        {theme === "dark" ? <Sun /> : <Moon />}
      </Button>
      <Button variant="ghost" size="icon-sm" aria-label="Sign out" onClick={() => void signOut()}>
        <LogOut />
      </Button>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, loading } = useSession();
  const [open, setOpen] = useState(false);
  const sidebar = (onNavigate?: () => void) => (
    <div className="flex h-full flex-col gap-6 p-4">
      <Link href="/" className="flex items-center gap-2 px-1 outline-none" onClick={onNavigate}>
        <Mark />
        <span className="text-[15px] font-semibold tracking-tight">AI Workmate</span>
      </Link>
      <NavList onNavigate={onNavigate} />
      <Footer />
    </div>
  );
  return (
    <div className="min-h-screen bg-background">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-card focus:px-3 focus:py-2">
        Skip to content
      </a>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 border-r border-sidebar-border bg-sidebar lg:block">
        {sidebar()}
      </aside>
      <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b bg-background/95 px-4 backdrop-blur lg:hidden">
        <Button variant="ghost" size="icon" aria-label="Open navigation" onClick={() => setOpen(true)}>
          <Menu />
        </Button>
        <Mark />
        <span className="font-semibold">AI Workmate</span>
      </header>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="left" className="w-64 bg-sidebar p-0">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          {sidebar(() => setOpen(false))}
        </SheetContent>
      </Sheet>
      <main id="main" className="lg:pl-60">
        <div className="mx-auto w-full max-w-[1200px] px-4 py-6 sm:px-6 lg:px-10 lg:py-8">
          {loading || !user ? (
            <div className="space-y-4">
              <Skeleton className="h-8 w-64" />
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-72 w-full" />
            </div>
          ) : (
            children
          )}
        </div>
      </main>
    </div>
  );
}
