export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

export const text = {
  label: "text-xs text-muted-foreground",
  body: "text-xs text-foreground",
  bodyMuted: "text-xs text-muted-foreground",
  caption: "text-xs text-muted-foreground",
  sectionTitle: "text-xs font-medium text-foreground",
  chip: "text-xs text-muted-foreground",
  metricLabel: "text-xs uppercase tracking-wider text-muted-foreground",
  metricValue: "text-sm font-medium text-foreground",
} as const;

export const control = {
  inputBase:
    "w-full rounded border border-border bg-input-background px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40",
  buttonGhost:
    "rounded border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground hover:bg-white/5",
  buttonPrimary:
    "rounded border border-primary/30 bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary transition-colors hover:bg-primary/20",
  tabButton: "px-3 py-2 text-xs transition-colors",
} as const;

export const shell = {
  card: "rounded-lg border border-border bg-card",
  panel: "rounded-lg border border-border overflow-hidden",
  headerRow: "flex items-center gap-2",
  sectionPad: "p-3",
  sectionGap: "space-y-4",
} as const;
