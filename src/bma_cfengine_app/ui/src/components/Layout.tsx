import React from "react";
import {
  Upload,
  Table2,
  Settings2,
  BarChart3,
  ChevronRight,
  RotateCcw,
  Clock,
  Layers,
  Sigma,
} from "lucide-react";
import { MONO } from "../lib/format";

export type Page = "intake" | "tape" | "setup" | "results" | "history" | "structuring" | "structured_analysis";

const NAV_ITEMS: { id: Page; label: string; icon: React.ElementType }[] = [
  { id: "intake", label: "Tape Intake", icon: Upload },
  { id: "tape", label: "Tape View", icon: Table2 },
  { id: "setup", label: "Run Setup", icon: Settings2 },
  { id: "results", label: "Results", icon: BarChart3 },
  { id: "history", label: "Run History", icon: Clock },
  { id: "structuring", label: "Structuring Studio", icon: Layers },
  { id: "structured_analysis", label: "Structured Deal Analysis", icon: Sigma },
];

interface LayoutProps {
  currentPage: Page;
  onNavigate: (page: Page) => void;
  pageTitle: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
  enabledPages?: Set<Page>;
  onReset?: () => void;
}

export default function Layout({
  currentPage,
  onNavigate,
  pageTitle,
  actions,
  children,
  enabledPages,
  onReset,
}: LayoutProps) {
  const enabled = enabledPages ?? new Set<Page>(["intake"]);

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="w-56 shrink-0 border-r border-border bg-[#0f172a] flex flex-col">
        <div className="px-4 py-4 border-b border-border">
          <h1
            className="text-primary font-semibold text-base tracking-tight"
            style={MONO}
          >
            BMA Engine
          </h1>
          <p className="text-muted-foreground text-[10px] mt-0.5">
            Cashflow Analytics
          </p>
        </div>
        <nav className="flex-1 py-2">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const active = currentPage === item.id;
            const disabled = !enabled.has(item.id);
            return (
              <button
                key={item.id}
                onClick={() => !disabled && onNavigate(item.id)}
                disabled={disabled}
                className={`w-full flex items-center gap-2.5 px-4 py-2 text-xs transition-colors ${
                  active
                    ? "bg-primary/10 text-primary border-r-2 border-primary"
                    : disabled
                    ? "text-muted-foreground/40 cursor-not-allowed"
                    : "text-muted-foreground hover:text-foreground hover:bg-white/5"
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                {item.label}
                {active && <ChevronRight className="w-3 h-3 ml-auto" />}
              </button>
            );
          })}
        </nav>
        {onReset && (
          <div className="px-3 py-2 border-t border-border">
            <button
              onClick={onReset}
              className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs text-muted-foreground hover:text-foreground hover:bg-white/5 transition-colors"
            >
              <RotateCcw className="w-3 h-3" />
              New Session
            </button>
          </div>
        )}
        <div className="px-4 py-3 border-t border-border text-[10px] text-muted-foreground">
          v0.1.0
        </div>
      </aside>

      {/* Main area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Action bar */}
        <header className="h-11 shrink-0 border-b border-border bg-[#0d1220] flex items-center px-4 gap-3">
          <h2 className="text-sm font-medium text-foreground">{pageTitle}</h2>
          <div className="flex-1" />
          {actions}
        </header>
        {/* Page content */}
        <main className="flex-1 min-h-0 overflow-auto p-4">{children}</main>
      </div>
    </div>
  );
}
