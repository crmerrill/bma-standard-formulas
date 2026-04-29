import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  listSolverTemplates,
  type ResolvedKnob,
  type SolverTemplateView,
  type TemplateInstantiationRequest,
} from "../../../../services/api";
import { text } from "../../../../components/system/ui";
import EmptyState from "../../../../components/EmptyState";
import LoadingState from "../../../../components/LoadingState";
import SolverTemplateCard from "./SolverTemplateCard";

interface Props {
  /**
   * Persisted deal id. When null, no templates are fetched (the deal
   * needs to be saved at least once to have a stable id).
   */
  dealId: string | null;
  /**
   * Product family from the collateral risk settings. Used (in a
   * future iteration) to filter templates whose `suitable_for_families`
   * doesn't include the current family.
   */
  productFamily: "AGENCY" | "PRIME_JUMBO" | "NON_QM_QRM" | "CUSTOM";
  /**
   * True while a run is in flight. The container disables all template
   * Run buttons during a run to avoid double-submits.
   */
  busy: boolean;
  /**
   * Parent-owned callback that runs the template end-to-end:
   * persist deal -> verify -> instantiate -> solve -> poll progress.
   * The container surface stays presentational; this lets the parent
   * own the single solver telemetry / polling loop without
   * duplication. The callback resolves with the run_id (or null on
   * failure) and the success message to display.
   */
  onRunTemplate: (
    templateId: string,
    request: TemplateInstantiationRequest,
  ) => Promise<{ ok: boolean; message: string }>;
}

/**
 * Container that renders the level-1 "Solve for X" cards on the
 * Structuring Studio solver tab.
 *
 * Responsibilities:
 *
 *   - Fetches `/deals/{id}/solver-templates` once on mount + on dealId
 *     change. The endpoint returns `SolverTemplateView`s with
 *     deal-aware defaults (current bond coupons, default ranges, etc.)
 *     already baked in -- no additional client-side resolution needed.
 *
 *   - Renders one `SolverTemplateCard` per returned template.
 *     Future: section by `template.category` to give the user a
 *     verb-led layout ("Balance the deal", "Size the bonds", "Hit a
 *     target", etc.).
 *
 *   - Tracks per-card status (idle / running / ok / error) so the user
 *     gets immediate feedback when a template runs, separate from the
 *     global solver telemetry on the legacy panel.
 */
export default function SolverTemplateCards({
  dealId,
  productFamily,
  busy,
  onRunTemplate,
}: Props) {
  const [views, setViews] = useState<SolverTemplateView[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [statusByTemplate, setStatusByTemplate] = useState<
    Record<string, { kind: "idle" | "running" | "ok" | "error"; message: string }>
  >({});

  const refresh = useCallback(async () => {
    if (!dealId) {
      setViews(null);
      return;
    }
    setLoading(true);
    setLoadError(null);
    try {
      const res = await listSolverTemplates(dealId);
      setViews(res.templates);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
      setViews(null);
    } finally {
      setLoading(false);
    }
  }, [dealId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Filter to templates whose suitable_for_families includes ANY or the
  // current product family. Most templates will be ANY for now.
  const visibleViews = useMemo(() => {
    if (!views) return [];
    const familyKey =
      productFamily === "CUSTOM" ? "ANY" : productFamily;
    return views.filter((v) => {
      const fams = v.template.suitable_for_families;
      if (!fams || fams.length === 0) return true;
      return fams.includes("ANY") || fams.includes(familyKey as never);
    });
  }, [views, productFamily]);

  const handleRunCard = useCallback(
    async (
      templateId: string,
      params: {
        primaryInputValue: number | string | boolean | null;
        lockedKnobIds: string[];
        knobOverrides: Record<string, ResolvedKnob>;
      },
    ) => {
      setStatusByTemplate((prev) => ({
        ...prev,
        [templateId]: { kind: "running", message: "Submitting solve…" },
      }));
      const request: TemplateInstantiationRequest = {
        primary_input_value: params.primaryInputValue,
        locked_knob_ids: params.lockedKnobIds,
        knob_overrides:
          Object.keys(params.knobOverrides).length > 0
            ? params.knobOverrides
            : undefined,
      };
      try {
        const result = await onRunTemplate(templateId, request);
        setStatusByTemplate((prev) => ({
          ...prev,
          [templateId]: result.ok
            ? { kind: "ok", message: result.message }
            : { kind: "error", message: result.message },
        }));
      } catch (err) {
        setStatusByTemplate((prev) => ({
          ...prev,
          [templateId]: {
            kind: "error",
            message: err instanceof Error ? err.message : String(err),
          },
        }));
      }
    },
    [onRunTemplate],
  );

  if (!dealId) {
    return (
      <EmptyState>
        <div className="space-y-1">
          <div className="text-foreground">Save the deal to use solver templates</div>
          <div>Templates need a saved deal to compute defaults from. Save your structure first, then return here.</div>
        </div>
      </EmptyState>
    );
  }

  if (loading) {
    return <LoadingState message="Loading solver templates…" />;
  }

  if (loadError) {
    return (
      <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
        Couldn&apos;t load solver templates — {loadError}
      </div>
    );
  }

  if (!visibleViews.length) {
    return (
      <EmptyState>
        <div className="space-y-1">
          <div className="text-foreground">No solver templates for this deal</div>
          <div>Templates will appear here as they become available for your product family.</div>
        </div>
      </EmptyState>
    );
  }

  return (
    <div className="space-y-3">
      <header className="flex items-center justify-between">
        <h3 className={text.sectionTitle}>Solve for…</h3>
        <span className="text-[11px] text-muted-foreground">
          Pick what you want, the solver figures out the rest.
        </span>
      </header>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {visibleViews.map((view) => {
          const id = view.template.template_id;
          return (
            <SolverTemplateCard
              key={id}
              view={view}
              busy={busy && statusByTemplate[id]?.kind !== "running"
                || statusByTemplate[id]?.kind === "running"}
              onRun={(params) => handleRunCard(id, params)}
              status={statusByTemplate[id] ?? { kind: "idle" }}
            />
          );
        })}
      </div>
    </div>
  );
}
