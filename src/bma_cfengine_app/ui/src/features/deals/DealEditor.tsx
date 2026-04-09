/**
 * DealEditor — composition root.
 *
 * Left: Blockly workspace (pay rules with targets inside)
 * Right: Property panel (synced bond/account editing) + collapsible IR preview
 * Drag handles resize sidebar width and (when IR is open) the split between Properties and IR.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, Code2, GripVertical, Save, Settings2 } from "lucide-react";
import { toast } from "sonner";
import BlocklyCanvas from "./BlocklyCanvas";
import PropertyPanel from "./PropertyPanel";
import { generateDealIR } from "./irGenerator";
import { applyDynamicColors } from "./blockColors";
import { MONO } from "../../lib/format";
import * as api from "../../services/api";

const SIDEBAR_MIN = 200;
const SIDEBAR_MAX = 640;
const PROPERTIES_PCT_MIN = 22;
const PROPERTIES_PCT_MAX = 82;

export default function DealEditor() {
  const [irJson, setIrJson] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [workspace, setWorkspace] = useState<any>(null);
  const [showIr, setShowIr] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(288);
  /** Share of right column height for Properties (%) when Deal IR is expanded */
  const [propertiesPct, setPropertiesPct] = useState(58);
  const [dealName, setDealName] = useState("Deal");
  const [savedDealId, setSavedDealId] = useState<string | null>(null);
  const [saveBusy, setSaveBusy] = useState(false);

  const rightColRef = useRef<HTMLDivElement>(null);
  const colDragRef = useRef<{ startX: number; startW: number } | null>(null);
  const rowDragRef = useRef<{ startY: number; startPct: number; height: number } | null>(null);

  const handleWorkspaceChange = useCallback((ws: any) => {
    setWorkspace(ws);
    applyDynamicColors(ws);
    try {
      const ir = generateDealIR(ws);
      setIrJson(JSON.stringify(ir, null, 2));
      setErrors([]);
      if (ir?.deal_name && typeof ir.deal_name === "string") {
        setDealName((prev) => (prev === "Deal" ? ir.deal_name : prev));
      }
    } catch (e: any) {
      setErrors([e.message || "Error generating IR"]);
    }
  }, []);

  const handleSaveDeal = useCallback(async () => {
    if (errors.length > 0 || !irJson.trim()) {
      toast.error("Fix workspace errors or add pay rules before saving.");
      return;
    }
    let ir: Record<string, unknown>;
    try {
      ir = JSON.parse(irJson) as Record<string, unknown>;
    } catch {
      toast.error("Deal IR is not valid JSON.");
      return;
    }
    ir.deal_name = dealName.trim() || "Deal";
    setSaveBusy(true);
    try {
      const res = await api.saveStudioDeal({
        deal_id: savedDealId,
        deal_name: dealName.trim() || "Deal",
        ir,
      });
      setSavedDealId(res.deal_id);
      toast.success(`Saved ${res.deal_name} as ${res.deal_id} (v${res.version})`);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaveBusy(false);
    }
  }, [errors.length, irJson, dealName, savedDealId]);

  useEffect(() => {
    const onColMove = (e: MouseEvent) => {
      const d = colDragRef.current;
      if (!d) return;
      const dx = e.clientX - d.startX;
      setSidebarWidth(Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, d.startW - dx)));
    };
    const onColUp = () => {
      colDragRef.current = null;
      document.body.style.removeProperty("cursor");
      document.body.style.removeProperty("user-select");
    };
    const onRowMove = (e: MouseEvent) => {
      const d = rowDragRef.current;
      if (!d || d.height <= 0) return;
      const dy = e.clientY - d.startY;
      const deltaPct = (dy / d.height) * 100;
      const next = d.startPct + deltaPct;
      setPropertiesPct(Math.min(PROPERTIES_PCT_MAX, Math.max(PROPERTIES_PCT_MIN, next)));
    };
    const onRowUp = () => {
      rowDragRef.current = null;
      document.body.style.removeProperty("cursor");
      document.body.style.removeProperty("user-select");
    };

    window.addEventListener("mousemove", onColMove);
    window.addEventListener("mouseup", onColUp);
    window.addEventListener("mousemove", onRowMove);
    window.addEventListener("mouseup", onRowUp);
    return () => {
      window.removeEventListener("mousemove", onColMove);
      window.removeEventListener("mouseup", onColUp);
      window.removeEventListener("mousemove", onRowMove);
      window.removeEventListener("mouseup", onRowUp);
    };
  }, []);

  const onColumnResizeStart = (e: React.MouseEvent) => {
    e.preventDefault();
    colDragRef.current = { startX: e.clientX, startW: sidebarWidth };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  };

  const onRowResizeStart = (e: React.MouseEvent) => {
    e.preventDefault();
    const h = rightColRef.current?.getBoundingClientRect().height ?? 0;
    rowDragRef.current = { startY: e.clientY, startPct: propertiesPct, height: h };
    document.body.style.cursor = "row-resize";
    document.body.style.userSelect = "none";
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <div className="flex shrink-0 flex-wrap items-center gap-2 px-1">
        <input
          type="text"
          value={dealName}
          onChange={(e) => setDealName(e.target.value)}
          placeholder="Deal name"
          className="min-w-[8rem] max-w-[16rem] flex-1 px-2 py-1 rounded border border-border bg-input-background text-xs text-foreground"
          style={MONO}
          aria-label="Deal name"
        />
        <button
          type="button"
          onClick={handleSaveDeal}
          disabled={saveBusy || errors.length > 0 || !irJson.trim()}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded border border-primary/30 bg-primary/10 text-primary text-xs font-medium hover:bg-primary/20 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Save className="w-3.5 h-3.5" />
          {saveBusy ? "Saving…" : "Save deal"}
        </button>
        {savedDealId && (
          <span className="text-[10px] text-muted-foreground" style={MONO}>
            {savedDealId}
          </span>
        )}
      </div>
      <div className="flex min-h-0 flex-1 gap-0">
      {/* Blockly workspace */}
      <BlocklyCanvas onChange={handleWorkspaceChange} />

      {/* Column resize handle */}
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize sidebar"
        onMouseDown={onColumnResizeStart}
        className="group relative w-2 shrink-0 cursor-col-resize flex items-center justify-center hover:bg-primary/15"
      >
        <div className="absolute inset-y-2 w-px bg-border group-hover:bg-primary/50" />
        <GripVertical className="w-3 h-3 text-muted-foreground/60 group-hover:text-muted-foreground relative z-[1]" />
      </div>

      {/* Right panel: properties + IR */}
      <div
        ref={rightColRef}
        style={{ width: sidebarWidth }}
        className="flex h-full min-h-0 min-w-0 shrink-0 flex-col"
      >
        {/* Property panel */}
        <div
          className={
            showIr
              ? "flex flex-col min-h-0 overflow-hidden rounded-md border border-border bg-[#0d1220]"
              : "flex flex-1 flex-col min-h-0 overflow-hidden rounded-md border border-border bg-[#0d1220]"
          }
          style={showIr ? { height: `${propertiesPct}%`, minHeight: 120 } : undefined}
        >
          <div className="shrink-0 flex items-center gap-1.5 px-3 pt-3 pb-2 border-b border-border/60">
            <Settings2 className="w-3.5 h-3.5 text-muted-foreground" />
            <span className="text-xs font-medium text-foreground">Properties</span>
          </div>
          <div className="flex-1 min-h-0 overflow-auto p-3 pt-2">
            <PropertyPanel workspace={workspace} />
          </div>
        </div>

        {showIr && (
          <div
            role="separator"
            aria-orientation="horizontal"
            aria-label="Resize Properties and Deal IR"
            onMouseDown={onRowResizeStart}
            className="group relative h-2 shrink-0 cursor-row-resize flex items-center justify-center hover:bg-primary/15"
          >
            <div className="absolute inset-x-2 h-px bg-border group-hover:bg-primary/50" />
            <GripVertical className="w-3 h-3 text-muted-foreground/60 group-hover:text-muted-foreground rotate-90 relative z-[1]" />
          </div>
        )}

        {/* Collapsible IR preview */}
        <div
          className={
            showIr
              ? "flex min-h-0 flex-1 flex-col overflow-hidden rounded-md border border-border bg-[#0d1220]"
              : "shrink-0 rounded-md border border-border bg-[#0d1220]"
          }
        >
          <button
            type="button"
            onClick={() => setShowIr(!showIr)}
            className="w-full flex items-center gap-1.5 px-3 py-2 text-xs text-muted-foreground hover:text-foreground transition-colors shrink-0"
          >
            {showIr ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            <Code2 className="w-3 h-3" />
            <span>Deal IR</span>
            {errors.length > 0 && (
              <span className="ml-auto text-destructive text-[10px]">error</span>
            )}
          </button>
          {showIr && (
            <pre
              className="flex-1 min-h-[120px] overflow-auto px-3 pb-2 text-[10px] leading-relaxed text-secondary-foreground border-t border-border"
              style={MONO}
            >
              {errors.length > 0
                ? errors.map((e, i) => <div key={i} className="text-destructive">{e}</div>)
                : irJson || "// Build the waterfall to see IR"
              }
            </pre>
          )}
        </div>
      </div>
      </div>
    </div>
  );
}
