/**
 * PropertyPanel — right-side panel showing bond/account properties.
 *
 * Scans the workspace for structuring entities and lets the user edit
 * canonical values in one place. Edits propagate to all matching blocks.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Info } from "lucide-react";
import { toast } from "sonner";
import { MONO } from "../../lib/format";
import * as api from "../../services/api";
import type { PoolSnapshotSummary, RunListItem, UploadLibraryItem } from "../../services/api";
import FormSelect from "../../components/FormSelect";
import CollateralRiskSettingsEditor from "./shared/CollateralRiskSettingsEditor";
import type { CollateralRiskSettings } from "./shared/riskSettings";
import CarryTieOutBanner from "./shared/CarryTieOutBanner";
import { computeStaticCarryTieOut } from "./shared/carryTieOut";

interface BondProps {
  name: string;
  bondType: string;
  payMode: "CASH_PAY" | "PIK";
  sizeDollars: number;
  sizePctPool: number;
  indexName: string;
  margin: number;
  coupon: number;
  accrual: string;
  blockIds: string[];
}

interface AccountProps {
  name: string;
  accountType: string;
  initialMode: string;
  initialAmt: number;
  blockIds: string[];
}

interface ResidualProps {
  name: string;
  sharePct: number;
  blockIds: string[];
}

interface TriggerProps {
  name: string;
  metric: string;
  threshold: number;
  blockIds: string[];
}

interface FeeProps {
  key: string;
  payee: string;
  source: string;
  basis: string;
  frequency: string;
  amount: number;
  blockIds: string[];
}

interface SplitProps {
  source: string;
  out1: string;
  out2: string;
  blockIds: string[];
}

const FEE_SOURCE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "COLLECTION", label: "Collection" },
  { value: "PRIN_COLLECTION", label: "Principal Collection" },
  { value: "INT_COLLECTION", label: "Interest Collection" },
  { value: "DISTRIBUTION", label: "Distribution" },
  { value: "RESERVE", label: "Reserve" },
  { value: "PREFUNDING", label: "Prefunding" },
  { value: "CAP_INTEREST", label: "Capitalized Interest" },
  { value: "EXPENSE", label: "Expense" },
  { value: "REINVESTMENT", label: "Reinvestment" },
  { value: "SWAP_HEDGE", label: "Swap / Hedge" },
  { value: "ESCROW", label: "Escrow" },
  { value: "YIELD_SUPPLEMENT", label: "Yield Supplement" },
];

interface PropertyPanelProps {
  workspace: any;
  collateralRiskSettings: CollateralRiskSettings;
  onCollateralRiskSettingsChange: (next: CollateralRiskSettings) => void;
  onOpenTape?: (uploadId: string, mappingId: string) => Promise<void> | void;
  onRunCashflow?: () => Promise<void> | void;
  canRunCashflow?: boolean;
  runCashflowBusy?: boolean;
  availableRuns: RunListItem[];
  availableTapes?: UploadLibraryItem[];
  poolSnapshots?: PoolSnapshotSummary[];
  /**
   * Lifted callback: PropertyPanel reports the live carry tie-out
   * status up to DealEditor so the Run/Solve buttons can gate on
   * BLOCK status with an explicit override-and-acknowledge action.
   * Receives `null` when the structure is degenerate (no bonds, zero
   * pool balance, etc.) and the banner is hidden.
   */
  onCarryTieOutStatusChange?: (
    status: "OK" | "WARN" | "BLOCK" | null,
    reason: string,
  ) => void;
  /** Phase 1i: pool inputs for PSA schedule derivation + stale indicator. */
  onPoolDerivationContextChange?: (
    ctx: {
      balance: number;
      wac_pct: number;
      term_months: number;
      horizon_months: number;
    } | null,
  ) => void;
  psaScheduleStale?: { stale: boolean; reason: string };
  showPsaScheduleTools?: boolean;
  onRederivePsaSchedules?: () => void | Promise<void>;
  scheduleDeriveBusy?: boolean;
}

function scanWorkspace(workspace: any): {
  bonds: BondProps[];
  accounts: AccountProps[];
  residuals: ResidualProps[];
  triggers: TriggerProps[];
  fees: FeeProps[];
  splits: SplitProps[];
} {
  const bondMap = new Map<string, BondProps>();
  const accountMap = new Map<string, AccountProps>();
  const residualMap = new Map<string, ResidualProps>();
  const triggerMap = new Map<string, TriggerProps>();
  const feeMap = new Map<string, FeeProps>();
  const splitMap = new Map<string, SplitProps>();

  if (!workspace) {
    return { bonds: [], accounts: [], residuals: [], triggers: [], fees: [], splits: [] };
  }

  const allBlocks = workspace.getAllBlocks(false);
  for (const block of allBlocks) {
    if (block.type === "bond_target") {
      const name = block.getFieldValue("NAME") || "?";
      if (!bondMap.has(name)) {
        bondMap.set(name, {
          name,
          bondType: block.getFieldValue("BOND_TYPE") || "FIXED",
          payMode: (block.getFieldValue("PAY_MODE") || "CASH_PAY") as "CASH_PAY" | "PIK",
          sizeDollars: Number(block.getFieldValue("FACE_AMT") || 0),
          sizePctPool: Number(block.getFieldValue("SIZE_PCT_POOL") || 0),
          indexName:
            (block.getFieldValue("BOND_TYPE") || "FIXED") === "FLOATING"
              ? (block.getFieldValue("INDEX_NAME") || "SOFR")
              : "",
          margin: Number(block.getFieldValue("MARGIN") || 0),
          coupon: block.getFieldValue("COUPON") || 0,
          accrual: block.getFieldValue("ACCRUAL") || "30_360",
          blockIds: [],
        });
      }
      bondMap.get(name)!.blockIds.push(block.id);
    } else if (block.type === "account_target") {
      const name = block.getFieldValue("ACCOUNT_TYPE") || "?";
      if (!accountMap.has(name)) {
        const legacyPct = block.getFieldValue("INITIAL_PCT");
        accountMap.set(name, {
          name,
          accountType: block.getFieldValue("ACCOUNT_TYPE") || "RESERVE",
          initialMode: block.getFieldValue("INITIAL_MODE") || "PCT_STACK",
          initialAmt:
            block.getFieldValue("INITIAL_AMT") ??
            (legacyPct != null ? legacyPct : 0),
          blockIds: [],
        });
      }
      accountMap.get(name)!.blockIds.push(block.id);
    } else if (block.type === "residual_target") {
      const name = block.getFieldValue("NAME") || "R";
      if (!residualMap.has(name)) {
        residualMap.set(name, {
          name,
          sharePct: Number(block.getFieldValue("SHARE_PCT") || 0),
          blockIds: [],
        });
      }
      residualMap.get(name)!.blockIds.push(block.id);
    } else if (block.type === "trigger_wrapper") {
      const name = block.getFieldValue("TRIGGER_NAME") || "TRIGGER";
      if (!triggerMap.has(name)) {
        triggerMap.set(name, {
          name,
          metric: block.getFieldValue("METRIC") || "CUSTOM",
          threshold: Number(block.getFieldValue("THRESHOLD") || 0),
          blockIds: [],
        });
      }
      triggerMap.get(name)!.blockIds.push(block.id);
    } else if (block.type === "pay_fee") {
      const payee = block.getFieldValue("PAYEE") || "SERVICER";
      const key = `${payee}:${block.getFieldValue("SOURCE") || "COLLECTION"}`;
      if (!feeMap.has(key)) {
        feeMap.set(key, {
          key,
          payee,
          source: block.getFieldValue("SOURCE") || "COLLECTION",
          basis: block.getFieldValue("BASIS") || "FIXED_DOLLAR",
          frequency: block.getFieldValue("FREQ") || "MONTHLY",
          amount: Number(block.getFieldValue("AMOUNT") || 0),
          blockIds: [],
        });
      }
      feeMap.get(key)!.blockIds.push(block.id);
    } else if (block.type === "split_account") {
      const source = block.getFieldValue("SOURCE") || "COLLECTION";
      if (!splitMap.has(source)) {
        splitMap.set(source, {
          source,
          out1: block.getFieldValue("OUT_1") || "Principal Collection",
          out2: block.getFieldValue("OUT_2") || "Interest Collection",
          blockIds: [],
        });
      }
      splitMap.get(source)!.blockIds.push(block.id);
    }
  }

  return {
    bonds: Array.from(bondMap.values()),
    accounts: Array.from(accountMap.values()),
    residuals: Array.from(residualMap.values()),
    triggers: Array.from(triggerMap.values()),
    fees: Array.from(feeMap.values()),
    splits: Array.from(splitMap.values()),
  };
}

function syncBondField(workspace: any, name: string, field: string, value: any) {
  if (!workspace) return;
  const allBlocks = workspace.getAllBlocks(false);
  for (const block of allBlocks) {
    if (block.type === "bond_target" && block.getFieldValue("NAME") === name) {
      const f = block.getField(field);
      if (f) f.setValue(value);
    }
  }
}

function syncBlockField(workspace: any, blockType: string, match: (block: any) => boolean, field: string, value: any) {
  if (!workspace) return;
  for (const block of workspace.getAllBlocks(false)) {
    if (block.type !== blockType || !match(block)) continue;
    const f = block.getField(field);
    if (f) f.setValue(value);
  }
}

function syncAccountField(workspace: any, accountType: string, field: string, value: any) {
  if (!workspace) return;
  const allBlocks = workspace.getAllBlocks(false);
  for (const block of allBlocks) {
    if (block.type === "account_target" && block.getFieldValue("ACCOUNT_TYPE") === accountType) {
      const f = block.getField(field);
      if (f) f.setValue(value);
    }
  }
}

function syncResidualField(workspace: any, residualName: string, field: string, value: any) {
  if (!workspace) return;
  for (const block of workspace.getAllBlocks(false)) {
    if (block.type === "residual_target" && block.getFieldValue("NAME") === residualName) {
      const f = block.getField(field);
      if (f) f.setValue(value);
    }
  }
}

function getStatementChain(parent: any, inputName: string): any[] {
  const out: any[] = [];
  let cur = parent?.getInputTargetBlock?.(inputName) ?? null;
  while (cur) {
    out.push(cur);
    cur = cur.getNextBlock?.() ?? null;
  }
  return out;
}

function inferResidualSharePct(workspace: any, residuals: ResidualProps[]): Record<string, number> {
  const residualNames = residuals.map((r) => r.name);
  if (!workspace || residualNames.length === 0) return {};
  const valid = new Set(residualNames);

  const manualWeights = residuals.map((r) => ({
    name: r.name,
    weight: Number.isFinite(r.sharePct) && r.sharePct > 0 ? r.sharePct : 0,
  }));
  const manualTotal = manualWeights.reduce((sum, item) => sum + item.weight, 0);
  if (manualTotal > 0) {
    return Object.fromEntries(
      manualWeights.map((item) => [item.name, (item.weight / manualTotal) * 100]),
    );
  }

  const weights = new Map<string, number>();
  residualNames.forEach((name) => weights.set(name, 0));

  for (const block of workspace.getAllBlocks(false)) {
    if (block.type !== "pay_pro_rata") continue;
    const payType = block.getFieldValue("PAY_TYPE") || "";
    if (payType !== "REMAINING") continue;
    const targets = getStatementChain(block, "TARGETS")
      .filter((t) => t.type === "residual_target")
      .map((t) => t.getFieldValue("NAME") || "R")
      .filter((name) => valid.has(name));
    if (targets.length === 0) continue;
    const unitWeight = 1 / targets.length;
    for (const name of targets) {
      weights.set(name, (weights.get(name) ?? 0) + unitWeight);
    }
  }

  const totalWeight = Array.from(weights.values()).reduce((sum, v) => sum + v, 0);
  if (totalWeight <= 0) {
    const equal = 100 / residualNames.length;
    return Object.fromEntries(residualNames.map((name) => [name, equal]));
  }
  const out: Record<string, number> = {};
  weights.forEach((weight, name) => {
    out[name] = (weight / totalWeight) * 100;
  });
  return out;
}

function inferCePctByBond(bonds: BondProps[], poolNotional: number): Record<string, number> {
  if (poolNotional <= 0 || bonds.length === 0) return {};
  const totalBonds = bonds.reduce((sum, bond) => sum + Math.max(0, bond.sizeDollars), 0);
  const residual = Math.max(0, poolNotional - totalBonds);
  const ceByBond: Record<string, number> = {};
  bonds.forEach((bond, idx) => {
    const below = bonds
      .slice(idx + 1)
      .reduce((sum, item) => sum + Math.max(0, item.sizeDollars), 0);
    ceByBond[bond.name] = ((below + residual) / poolNotional) * 100;
  });
  return ceByBond;
}

export default function PropertyPanel({
  workspace,
  collateralRiskSettings,
  onCollateralRiskSettingsChange,
  onOpenTape,
  onRunCashflow,
  canRunCashflow = false,
  runCashflowBusy = false,
  availableRuns,
  availableTapes = [],
  poolSnapshots = [],
  onCarryTieOutStatusChange,
  onPoolDerivationContextChange,
  psaScheduleStale,
  showPsaScheduleTools = false,
  onRederivePsaSchedules,
  scheduleDeriveBusy = false,
}: PropertyPanelProps) {
  const [bonds, setBonds] = useState<BondProps[]>([]);
  const [accounts, setAccounts] = useState<AccountProps[]>([]);
  const [residuals, setResiduals] = useState<ResidualProps[]>([]);
  const [triggers, setTriggers] = useState<TriggerProps[]>([]);
  const [fees, setFees] = useState<FeeProps[]>([]);
  const [splits, setSplits] = useState<SplitProps[]>([]);
  const [poolNotional, setPoolNotional] = useState<number>(0);
  const [ceInputByBond, setCeInputByBond] = useState<Record<string, string>>({});
  const [tapePoolNotional, setTapePoolNotional] = useState<number | null>(null);
  const [loadingTapePoolNotional, setLoadingTapePoolNotional] = useState(false);
  /** Tape-derived collateral economics consumed by the live carry tie-out banner. */
  const [tapeCollateralStats, setTapeCollateralStats] = useState<{
    wac_pct: number;
    wam_months: number;
  } | null>(null);
  const [bondValidationError, setBondValidationError] = useState<string | null>(null);
  const [solveDriver, setSolveDriver] = useState<"ce" | "notional" | "notional_pct_pool">("ce");

  const refresh = useCallback(() => {
    const { bonds: b, accounts: a, residuals: r, triggers: t, fees: f, splits: s } = scanWorkspace(workspace);
    setBonds(b);
    setAccounts(a);
    setResiduals(r);
    setTriggers(t);
    setFees(f);
    setSplits(s);
  }, [workspace]);

  useEffect(() => {
    refresh();
    if (!workspace) return;
    const listener = () => setTimeout(refresh, 100);
    workspace.addChangeListener(listener);
    return () => workspace.removeChangeListener(listener);
  }, [workspace, refresh]);

  useEffect(() => {
    let cancelled = false;
    const tapeId = collateralRiskSettings.tapeId.trim();
    const mappingId = collateralRiskSettings.tapeMappingId.trim();
    if (!tapeId || !mappingId) {
      setTapePoolNotional(null);
      setPoolNotional(0);
      setLoadingTapePoolNotional(false);
      return () => {
        cancelled = true;
      };
    }
    setLoadingTapePoolNotional(true);
    api.getTapeStats(tapeId, mappingId)
      .then((stats) => {
        if (cancelled) return;
        const totalBalance = Number(stats.total_balance) || 0;
        setTapePoolNotional(totalBalance > 0 ? totalBalance : null);
        setPoolNotional(totalBalance > 0 ? totalBalance : 0);
        const wac = Number(stats.wac);
        const wam = Number(stats.wam);
        if (Number.isFinite(wac) && wac > 0 && Number.isFinite(wam) && wam > 0) {
          setTapeCollateralStats({ wac_pct: wac, wam_months: wam });
        } else {
          setTapeCollateralStats(null);
        }
      })
      .catch(() => {
        if (cancelled) return;
        setTapePoolNotional(null);
        setPoolNotional(0);
        setTapeCollateralStats(null);
      })
      .finally(() => {
        if (!cancelled) setLoadingTapePoolNotional(false);
      });
    return () => {
      cancelled = true;
    };
  }, [collateralRiskSettings.tapeId, collateralRiskSettings.tapeMappingId]);

  const syncAllPctFromPoolNotional = useCallback(() => {
    if (poolNotional <= 0) {
      toast.error("Collateral $ must be available from tape to solve.");
      return;
    }
    for (const bond of bonds) {
      syncBondField(workspace, bond.name, "SIZE_PCT_POOL", (Math.max(0, bond.sizeDollars) / poolNotional) * 100);
    }
    refresh();
    toast.success("Updated bond %Pool values from pool notional.");
  }, [bonds, poolNotional, workspace, refresh]);

  const setBondSizeDollarsDirect = useCallback(
    (bondName: string, nextSizeDollars: number) => {
      const next = Math.max(0, nextSizeDollars);
      syncBondField(workspace, bondName, "FACE_AMT", next);
      if (poolNotional > 0) {
        syncBondField(workspace, bondName, "SIZE_PCT_POOL", (next / poolNotional) * 100);
      }
      refresh();
    },
    [workspace, poolNotional, refresh],
  );

  const setBondSizePctDirect = useCallback(
    (bondName: string, nextPct: number) => {
      const pct = Math.max(0, nextPct);
      syncBondField(workspace, bondName, "SIZE_PCT_POOL", pct);
      if (poolNotional > 0) {
        syncBondField(workspace, bondName, "FACE_AMT", (pct / 100) * poolNotional);
      }
      refresh();
    },
    [workspace, poolNotional, refresh],
  );

  // UI row order is treated as senior -> junior for CE ladder solve.
  const orderedBonds = useMemo(() => [...bonds], [bonds]);

  useEffect(() => {
    if (orderedBonds.length === 0) return;
    const implied = inferCePctByBond(orderedBonds, poolNotional);
    setCeInputByBond((prev) => {
      const next: Record<string, string> = {};
      orderedBonds.forEach((bond) => {
        next[bond.name] = prev[bond.name] ?? (implied[bond.name] ?? 0).toFixed(2);
      });
      return next;
    });
  }, [orderedBonds, poolNotional]);

  const solveStackForBondSize = useCallback(
    (bondName: string, targetSize: number): boolean => {
      if (poolNotional <= 0) {
        setBondValidationError("Collateral $ must be available from tape to solve.");
        return false;
      }
      const clamped = Math.floor(Math.max(0, Math.min(poolNotional, targetSize)));
      syncBondField(workspace, bondName, "FACE_AMT", clamped);
      // Keep all other bond dollar targets as-entered; recompute only derived %Pool values.
      orderedBonds.forEach((bond) => {
        const nextSize =
          bond.name === bondName
            ? clamped
            : Math.floor(Math.max(0, Number(bond.sizeDollars) || 0));
        syncBondField(workspace, bond.name, "FACE_AMT", nextSize);
        syncBondField(workspace, bond.name, "SIZE_PCT_POOL", (nextSize / poolNotional) * 100);
      });

      refresh();
      const nextTotal = orderedBonds.reduce(
        (sum, bond) => sum + (bond.name === bondName ? clamped : Math.floor(Math.max(0, bond.sizeDollars))),
        0,
      );
      if (nextTotal > poolNotional + 0.01) {
        setBondValidationError(
          `Bond stack exceeds Collateral $ by ${(nextTotal - poolNotional).toFixed(2)}.`,
        );
      } else {
        setBondValidationError(null);
      }
      return true;
    },
    [orderedBonds, poolNotional, workspace, refresh],
  );

  const solveCeStack = useCallback(
    (
      override?: { bondName: string; targetPct: number },
      explicitTargets?: Record<string, string>,
    ): boolean => {
      if (orderedBonds.length === 0) return false;
      if (poolNotional <= 0) {
        setBondValidationError("Collateral $ must be available from tape to solve.");
        return false;
      }
      const total = orderedBonds.reduce((sum, bond) => sum + Math.max(0, bond.sizeDollars), 0);
      const ceCurrentByBond = new Map<string, number>();
      const currentResidual = Math.max(0, poolNotional - total);
      orderedBonds.forEach((bond, idx) => {
        const below = orderedBonds
          .slice(idx + 1)
          .reduce((sum, item) => sum + Math.max(0, item.sizeDollars), 0);
        ceCurrentByBond.set(bond.name, poolNotional > 0 ? ((below + currentResidual) / poolNotional) * 100 : 0);
      });

      const targets: number[] = [];
      for (let i = 0; i < orderedBonds.length; i += 1) {
        const bond = orderedBonds[i];
        const overrideHit = override && override.bondName === bond.name;
        const raw = overrideHit
          ? String(override.targetPct)
          : (explicitTargets?.[bond.name] ?? ceInputByBond[bond.name] ?? "");
        const parsed = Number(raw);
        const targetPct =
          Number.isFinite(parsed) && parsed >= 0 && parsed < 100
            ? parsed
            : (ceCurrentByBond.get(bond.name) ?? 0);
        targets.push(targetPct / 100);
      }

      for (let i = 0; i < targets.length - 1; i += 1) {
        if (targets[i] < targets[i + 1]) {
          setBondValidationError(
            "CE targets must be non-increasing from senior to junior tranches (top row to bottom row).",
          );
          return false;
        }
      }

      const solvedSizes: number[] = [];
      solvedSizes.push((1 - targets[0]) * poolNotional);
      for (let i = 1; i < orderedBonds.length; i += 1) {
        solvedSizes.push((targets[i - 1] - targets[i]) * poolNotional);
      }

      if (solvedSizes.some((x) => !Number.isFinite(x) || x < 0)) {
        setBondValidationError("CE target set is infeasible for the current tranche order.");
        return false;
      }

      orderedBonds.forEach((bond, idx) => {
        const size = Math.floor(solvedSizes[idx] ?? 0);
        syncBondField(workspace, bond.name, "FACE_AMT", size);
        syncBondField(workspace, bond.name, "SIZE_PCT_POOL", (size / poolNotional) * 100);
      });
      refresh();
      setBondValidationError(null);
      return true;
    },
    [orderedBonds, poolNotional, ceInputByBond, workspace, refresh],
  );

  const seedCeTargetsForProfile = useCallback(() => {
    if (orderedBonds.length === 0) return;
    const ladder = (() => {
      switch (collateralRiskSettings.productFamily) {
        case "NON_QM_QRM":
          return [20, 12, 8, 5, 3];
        case "PRIME_JUMBO":
          return [10, 6, 4, 2.5, 1.5];
        case "AGENCY":
          return [5, 3, 2, 1.25, 0.75];
        case "CUSTOM":
        default:
          return [10, 6, 4, 2.5, 1.5];
      }
    })();
      const next: Record<string, string> = {};
    orderedBonds.forEach((bond, idx) => {
      next[bond.name] = String(ladder[Math.min(idx, ladder.length - 1)]);
    });
    setCeInputByBond(next);
      solveCeStack(undefined, next);
    const label =
      collateralRiskSettings.productFamily === "NON_QM_QRM"
        ? "Non-QM/QRM"
        : collateralRiskSettings.productFamily === "PRIME_JUMBO"
          ? "Prime Jumbo"
          : collateralRiskSettings.productFamily === "AGENCY"
            ? "Agency"
            : "Custom";
    toast.success(`Seeded ${label} CE targets.`);
  }, [orderedBonds, collateralRiskSettings.productFamily, solveCeStack]);

  const familyLabel =
    collateralRiskSettings.productFamily === "NON_QM_QRM"
      ? "Non-QM/QRM"
      : collateralRiskSettings.productFamily === "PRIME_JUMBO"
        ? "Prime"
        : collateralRiskSettings.productFamily === "AGENCY"
          ? "Agency"
          : "Custom";
  const totalBondSize = orderedBonds.reduce((sum, bond) => sum + Math.max(0, bond.sizeDollars), 0);
  const residualNames = residuals.map((r) => r.name).sort((a, b) => a.localeCompare(b));
  const residualByName = useMemo(
    () => Object.fromEntries(residuals.map((r) => [r.name, r])),
    [residuals],
  );
  const residualShareByName = useMemo(
    () => inferResidualSharePct(workspace, residuals),
    [workspace, residuals],
  );
  const derivedCeByBond = useMemo(
    () => inferCePctByBond(orderedBonds, poolNotional),
    [orderedBonds, poolNotional],
  );
  const residualCount = residuals.reduce((sum, r) => sum + r.blockIds.length, 0);
  const residualSize = Math.max(0, poolNotional - totalBondSize);

  useEffect(() => {
    if (poolNotional <= 0 || orderedBonds.length === 0) {
      if (!loadingTapePoolNotional) {
        setBondValidationError("Collateral $ unavailable. Select a tape with a saved mapping.");
      }
      return;
    }
    const overPctBond = orderedBonds.find((bond) => bond.sizePctPool > 100.0001);
    if (overPctBond) {
      setBondValidationError(
        `${overPctBond.name} exceeds 100% of Collateral $ (${overPctBond.sizePctPool.toFixed(2)}%).`,
      );
      return;
    }
    const overSizeBond = orderedBonds.find((bond) => bond.sizeDollars > poolNotional + 0.01);
    if (overSizeBond) {
      setBondValidationError(
        `${overSizeBond.name} size exceeds Collateral $ (${overSizeBond.sizeDollars.toFixed(2)}).`,
      );
      return;
    }
    const totalBonds = orderedBonds.reduce((sum, bond) => sum + Math.max(0, bond.sizeDollars), 0);
    if (totalBonds > poolNotional + 0.01) {
      setBondValidationError(
        `Bond stack exceeds Collateral $ by ${(totalBonds - poolNotional).toFixed(2)}.`,
      );
    } else {
      setBondValidationError((prev) => {
        if (!prev) return prev;
        return prev.includes("exceeds Collateral $") ? null : prev;
      });
    }
  }, [poolNotional, orderedBonds, loadingTapePoolNotional]);

  // ------------------------------------------------------------------
  // Live static carry tie-out banner.
  //
  // Pure analytic projection: pool yield ~= WAC - servicing, constant
  // CPR amortization, sequential principal allocation across cash
  // bonds. Fast enough to recompute on every PropertyPanel render so
  // the banner reflects the live structure without an engine
  // round-trip. The post-run engine-truth tie-out (Phase 4, Python
  // `carry_tieout.py`) is the authoritative number once a base run
  // exists.
  //
  // Servicing default: 50bps (industry standard for agency MBS;
  // typical for prime jumbo / Non-QM private-label too). Surfacing a
  // user-configurable servicing input is a follow-up.
  // ------------------------------------------------------------------
  const carryTieOutResult = useMemo(() => {
    if (!tapeCollateralStats || poolNotional <= 0 || bonds.length === 0) {
      return null;
    }
    return computeStaticCarryTieOut({
      pool: {
        balance: poolNotional,
        wac_pct: tapeCollateralStats.wac_pct,
        servicing_pct: 0.5,
        remaining_term_months: Math.max(
          Math.round(tapeCollateralStats.wam_months),
          12,
        ),
        cpr_pct: collateralRiskSettings.newRiskParams.cpr,
      },
      bonds: bonds.map((b) => ({
        name: b.name,
        notional: Math.max(b.sizeDollars, 0),
        coupon_pct: b.coupon,
        kind: b.bondType,
        pay_mode: b.payMode,
      })),
    });
  }, [tapeCollateralStats, poolNotional, bonds, collateralRiskSettings.newRiskParams.cpr]);

  useEffect(() => {
    if (!onPoolDerivationContextChange) return;
    if (poolNotional <= 0 || !tapeCollateralStats) {
      onPoolDerivationContextChange(null);
      return;
    }
    const wac = tapeCollateralStats.wac_pct;
    const wam = Math.max(1, Math.round(tapeCollateralStats.wam_months));
    const horizon = Math.max(1, Math.round(collateralRiskSettings.newRiskParams.horizonMonths));
    if (!Number.isFinite(wac) || wac <= 0) {
      onPoolDerivationContextChange(null);
      return;
    }
    onPoolDerivationContextChange({
      balance: poolNotional,
      wac_pct: wac,
      term_months: wam,
      horizon_months: horizon,
    });
  }, [
    poolNotional,
    tapeCollateralStats,
    collateralRiskSettings.newRiskParams.horizonMonths,
    onPoolDerivationContextChange,
  ]);

  // Bubble up the carry status to DealEditor so the Run/Solve buttons
  // can gate on a BLOCK condition (Phase 5 of the carry tie-out plan).
  useEffect(() => {
    if (!onCarryTieOutStatusChange) return;
    if (!carryTieOutResult || carryTieOutResult.is_degenerate) {
      onCarryTieOutStatusChange(null, "");
      return;
    }
    onCarryTieOutStatusChange(carryTieOutResult.status, carryTieOutResult.reason);
  }, [carryTieOutResult, onCarryTieOutStatusChange]);

  return (
    <div className="flex flex-col gap-3 text-xs">
      {carryTieOutResult && !carryTieOutResult.is_degenerate && (
        <CarryTieOutBanner
          result={carryTieOutResult}
          contextLabel="Live carry tie-out"
        />
      )}
      {showPsaScheduleTools && onRederivePsaSchedules && (
        <div
          className={`rounded-md border px-3 py-2 ${
            psaScheduleStale?.stale
              ? "border-amber-500/50 bg-amber-500/10 text-amber-100"
              : "border-border/80 bg-muted/20 text-muted-foreground"
          }`}
        >
          <div className="font-medium text-foreground">PAC / TAC PSA schedules</div>
          <p className="mt-1 text-[11px] leading-snug">
            {psaScheduleStale?.stale
              ? psaScheduleStale.reason
              : "Schedules match current pool, speeds, and sizes (or Blockly placeholders only)."}
            {" "}Collateral stats from tape drive the envelope projection.
          </p>
          <button
            type="button"
            className="mt-2 rounded border border-border px-2 py-1 text-[11px] text-foreground hover:bg-muted/40 disabled:opacity-50"
            disabled={Boolean(scheduleDeriveBusy)}
            onClick={() => void onRederivePsaSchedules()}
          >
            {scheduleDeriveBusy ? "Deriving…" : "Re-derive schedules now"}
          </button>
        </div>
      )}
      <SectionCard title="Collateral & Risk">
        <CollateralRiskSettingsEditor
          value={collateralRiskSettings}
          onChange={onCollateralRiskSettingsChange}
          availableRuns={availableRuns}
          availableTapes={availableTapes}
          poolSnapshots={poolSnapshots}
          onOpenTape={onOpenTape}
          onRunCashflow={onRunCashflow}
          canRunCashflow={canRunCashflow}
          runCashflowBusy={runCashflowBusy}
          title="Mirrored risk settings"
        />
      </SectionCard>

      {fees.length > 0 && (
        <SectionCard
          title="Fees"
          tooltipText="Fee input basis: Input is an annual manual value; Frequency controls pay cadence. Pool BPS uses annual bps on collateral balance; Fixed $ and Per Loan $ are annual amounts reconciled to the selected frequency."
        >
          <div className="overflow-x-auto">
            <div className="min-w-[520px]">
              <div className="grid grid-cols-[108px_108px_124px_108px_92px_32px] gap-2 px-2 py-1 text-xs text-muted-foreground uppercase tracking-wider border-b border-border">
                <span>Payee</span>
                <span>Source</span>
                <span>Type</span>
                <span>Frequency</span>
                <span>Input (annual)</span>
                <span className="text-right">x</span>
              </div>
              {fees.map((f) => (
                <div
                  key={f.key}
                  className="grid grid-cols-[108px_108px_124px_108px_92px_32px] gap-2 items-center px-2 py-1.5 border-b border-border/70"
                >
                  <span className="text-foreground" style={MONO}>{f.payee}</span>
                  <FormSelect
                    value={f.source}
                    onChange={(e) => {
                      syncBlockField(
                        workspace,
                        "pay_fee",
                        (block) =>
                          (block.getFieldValue("PAYEE") || "SERVICER") === f.payee
                          && (block.getFieldValue("SOURCE") || "COLLECTION") === f.source,
                        "SOURCE",
                        e.target.value,
                      );
                      refresh();
                    }}
                  >
                    {FEE_SOURCE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </FormSelect>
                  <FormSelect
                    value={f.basis}
                    onChange={(e) => {
                      syncBlockField(
                        workspace,
                        "pay_fee",
                        (block) =>
                          (block.getFieldValue("PAYEE") || "SERVICER") === f.payee
                          && (block.getFieldValue("SOURCE") || "COLLECTION") === f.source,
                        "BASIS",
                        e.target.value,
                      );
                      refresh();
                    }}
                  >
                    <option value="PCT_POOL">Pool BPS</option>
                    <option value="FIXED_DOLLAR">Fixed $</option>
                    <option value="PER_LOAN">Per Loan $</option>
                  </FormSelect>
                  <FormSelect
                    value={f.frequency}
                    onChange={(e) => {
                      syncBlockField(
                        workspace,
                        "pay_fee",
                        (block) =>
                          (block.getFieldValue("PAYEE") || "SERVICER") === f.payee
                          && (block.getFieldValue("SOURCE") || "COLLECTION") === f.source,
                        "FREQ",
                        e.target.value,
                      );
                      refresh();
                    }}
                  >
                    <option value="MONTHLY">Monthly</option>
                    <option value="QUARTERLY">Quarterly</option>
                    <option value="ANNUAL">Annual</option>
                  </FormSelect>
                  <input
                    type="number"
                    value={f.amount}
                    step={0.01}
                    onChange={(e) => {
                      syncBlockField(
                        workspace,
                        "pay_fee",
                        (block) =>
                          (block.getFieldValue("PAYEE") || "SERVICER") === f.payee
                          && (block.getFieldValue("SOURCE") || "COLLECTION") === f.source,
                        "AMOUNT",
                        Number(e.target.value) || 0,
                      );
                      refresh();
                    }}
                    className="w-full px-1.5 py-1 bg-input-background border border-border rounded text-foreground"
                    style={MONO}
                  />
                  <span className="text-muted-foreground text-right">{f.blockIds.length}</span>
                </div>
              ))}
            </div>
          </div>
        </SectionCard>
      )}

      {bonds.length > 0 && (
        <SectionCard title="Bonds">
          <div className="mb-2 grid grid-cols-[1fr_auto] items-center gap-2">
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              Collateral $
              <span
                className="inline-flex w-40 items-center px-1.5 py-1 bg-input-background border border-border rounded text-foreground"
                style={MONO}
              >
                {poolNotional > 0 ? poolNotional.toLocaleString() : "Unavailable"}
              </span>
            </label>
            <div className="flex items-center gap-1">
              <span className="text-xs text-muted-foreground px-1">Driver</span>
              <div className="flex items-center rounded border border-border overflow-hidden">
                <button
                  type="button"
                  onClick={() => setSolveDriver("ce")}
                  className={solveDriver === "ce"
                    ? "px-2 py-1 text-xs bg-primary/20 text-primary"
                    : "px-2 py-1 text-xs text-muted-foreground hover:text-foreground"}
                >
                  CE
                </button>
                <button
                  type="button"
                  onClick={() => setSolveDriver("notional")}
                  className={solveDriver === "notional"
                    ? "px-2 py-1 text-xs bg-primary/20 text-primary"
                    : "px-2 py-1 text-xs text-muted-foreground hover:text-foreground"}
                >
                  Size $
                </button>
                <button
                  type="button"
                  onClick={() => setSolveDriver("notional_pct_pool")}
                  className={solveDriver === "notional_pct_pool"
                    ? "px-2 py-1 text-xs bg-primary/20 text-primary"
                    : "px-2 py-1 text-xs text-muted-foreground hover:text-foreground"}
                >
                  %Pool
                </button>
              </div>
              <button
                type="button"
                onClick={seedCeTargetsForProfile}
                className="px-2 py-1 rounded border border-border text-xs text-muted-foreground hover:text-foreground"
              >
                Seed CE targets ({familyLabel})
              </button>
              <button
                type="button"
                onClick={syncAllPctFromPoolNotional}
                className="px-2 py-1 rounded border border-border text-xs text-muted-foreground hover:text-foreground"
              >
                Recalc %Pool
              </button>
            </div>
          </div>
          <div className="mb-2 text-xs text-muted-foreground">
            {loadingTapePoolNotional
              ? "Resolving tape notional..."
              : tapePoolNotional && tapePoolNotional > 0
                ? `Tape collateral loaded: ${tapePoolNotional.toLocaleString()}`
                : "Tape collateral unavailable. Select tape + mapping to enable solve."}
          </div>
          {bondValidationError && (
            <div className="mb-2 rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-xs text-amber-100">
              Validation: {bondValidationError}
            </div>
          )}
          <div className="overflow-x-auto">
            <div className="min-w-[620px]">
              <div className="grid grid-cols-[64px_72px_96px_72px_82px_82px_72px_24px] gap-2 px-2 py-1 text-xs text-muted-foreground uppercase tracking-wider border-b border-border">
                <span>Name</span>
                <span>Type</span>
                <span>Size ($)</span>
                <span>%Pool</span>
                <span>CE</span>
                <span>Index</span>
                <span>Coupon</span>
                <span className="text-right">x</span>
              </div>
              {bonds.map((b) => (
                <div key={b.name} className="border-b border-border/70">
                  <div className="grid grid-cols-[64px_72px_96px_72px_82px_82px_72px_24px] gap-2 items-center px-2 py-1.5">
                    <span className="font-medium text-foreground" style={MONO}>{b.name}</span>
                    <span className="text-muted-foreground">{b.bondType}</span>
                    <input
                      type="number"
                      value={b.sizeDollars}
                      onChange={(e) => {
                        if (solveDriver !== "notional") return;
                        const next = parseFloat(e.target.value) || 0;
                        solveStackForBondSize(b.name, next);
                      }}
                      className="w-full px-1.5 py-1 bg-input-background border border-border rounded text-foreground"
                      style={MONO}
                      disabled={solveDriver !== "notional"}
                    />
                    <input
                      type="number"
                      value={b.sizePctPool}
                      onChange={(e) => {
                        if (solveDriver !== "notional_pct_pool") return;
                        const pct = Math.max(0, parseFloat(e.target.value) || 0);
                        solveStackForBondSize(b.name, (pct * poolNotional) / 100);
                      }}
                      className="w-full px-1.5 py-1 bg-input-background border border-border rounded text-foreground"
                      style={MONO}
                      disabled={solveDriver !== "notional_pct_pool"}
                    />
                    <input
                      type="number"
                      value={ceInputByBond[b.name] ?? (derivedCeByBond[b.name] ?? 0).toFixed(2)}
                      onChange={(e) => {
                        if (solveDriver !== "ce") return;
                        setCeInputByBond((prev) => ({ ...prev, [b.name]: e.target.value }));
                        const targetPct = Number(e.target.value);
                        if (!Number.isFinite(targetPct) || targetPct < 0 || targetPct >= 100) {
                          setBondValidationError("CE input must be between 0 and 100.");
                          return;
                        }
                        solveCeStack({ bondName: b.name, targetPct });
                      }}
                      className="w-full px-1.5 py-1 bg-input-background border border-border rounded text-foreground"
                      style={MONO}
                      placeholder="%"
                      disabled={solveDriver !== "ce"}
                    />
                    {b.bondType === "FLOATING" ? (
                      <input
                        value={b.indexName}
                        onChange={(e) => {
                          syncBondField(workspace, b.name, "INDEX_NAME", e.target.value);
                          refresh();
                        }}
                        className="w-full px-1.5 py-1 bg-input-background border border-border rounded text-foreground"
                        style={MONO}
                      />
                    ) : (
                      <span className="text-muted-foreground text-center">—</span>
                    )}
                    <input
                      type="number"
                      value={b.coupon}
                      step={0.01}
                      onChange={(e) => {
                        const v = parseFloat(e.target.value) || 0;
                        syncBondField(workspace, b.name, "COUPON", v);
                        refresh();
                      }}
                      className="w-full px-1.5 py-1 bg-input-background border border-border rounded text-foreground"
                      style={MONO}
                    />
                    <span className="text-muted-foreground text-right">{b.blockIds.length}</span>
                  </div>
                  <div className="grid grid-cols-[160px_1fr] gap-2 px-2 pb-2">
                    <FormSelect
                      value={b.payMode}
                      onChange={(e) => {
                        syncBondField(workspace, b.name, "PAY_MODE", e.target.value);
                        refresh();
                      }}
                    >
                      <option value="CASH_PAY">Cash Pay</option>
                      <option value="PIK">PIK</option>
                    </FormSelect>
                    <span className="text-muted-foreground px-1 py-1">
                      PAC/TAC are authored via schedule pay rules; PIK mode enables Z-style accrual semantics.
                    </span>
                  </div>
                </div>
              ))}
              <div className="px-2 py-1 text-xs text-muted-foreground border-b border-border/70">
                CE and %Pool are recomputed from one stack model using Collateral $ and residual.
              </div>
              <div className="grid grid-cols-[64px_72px_96px_72px_82px_82px_72px_24px] gap-2 items-center px-2 py-1.5 border-b border-border/70 bg-background/40">
                <span className="font-medium text-foreground" style={MONO}>R</span>
                <span className="text-muted-foreground">RESIDUAL</span>
                <span className="px-1.5 py-1 text-foreground" style={MONO}>{residualSize.toFixed(2)}</span>
                <span className="px-1.5 py-1 text-foreground" style={MONO}>
                  {poolNotional > 0 ? ((residualSize / poolNotional) * 100).toFixed(4) : "0.0000"}
                </span>
                <span className="px-1.5 py-1 text-muted-foreground">0.00</span>
                <span className="text-muted-foreground text-center">—</span>
                <span className="text-muted-foreground text-center">—</span>
                <span className="text-muted-foreground text-right">{residualCount}</span>
              </div>
              {residualNames.map((name) => (
                <div
                  key={name}
                  className="grid grid-cols-[64px_72px_96px_72px_82px_82px_72px_24px] gap-2 items-center px-2 py-1.5 border-b border-border/70 bg-background/20"
                >
                  <span className="font-medium text-foreground" style={MONO}>{name}</span>
                  <span className="text-muted-foreground">Pro-rata R</span>
                  <span className="px-1.5 py-1 text-foreground" style={MONO}>
                    {(residualSize * ((residualShareByName[name] ?? 0) / 100)).toFixed(2)}
                  </span>
                  <span className="px-1.5 py-1 text-foreground" style={MONO}>
                    {poolNotional > 0
                      ? ((residualSize * ((residualShareByName[name] ?? 0) / 100) / poolNotional) * 100).toFixed(4)
                      : "0.0000"}
                  </span>
                  <input
                    type="number"
                    value={residualByName[name]?.sharePct ?? 0}
                    step={0.01}
                    min={0}
                    onChange={(e) => {
                      const next = Math.max(0, Number(e.target.value) || 0);
                      syncResidualField(workspace, name, "SHARE_PCT", next);
                      refresh();
                    }}
                    className="w-full px-1.5 py-1 bg-input-background border border-border rounded text-foreground"
                    style={MONO}
                    title="Residual share weight (%R)"
                  />
                  <span className="text-muted-foreground text-center">—</span>
                  <span className="text-muted-foreground text-center">—</span>
                  <span className="text-muted-foreground text-right">
                    {residuals.find((r) => r.name === name)?.blockIds.length ?? 1}
                  </span>
                </div>
              ))}
              {residualNames.length > 0 && (
                <div className="px-2 py-1 text-xs text-muted-foreground border-b border-border/70">
                  Residual %R inputs are editable weights and are normalized across all residual recipients.
                </div>
              )}
            </div>
          </div>
        </SectionCard>
      )}

      {accounts.length > 0 && (
        <SectionCard title="Accounts">
          <div className="overflow-x-auto">
            <div className="min-w-[420px]">
              <div className="grid grid-cols-[160px_120px_100px_32px] gap-2 px-2 py-1 text-xs text-muted-foreground uppercase tracking-wider border-b border-border">
                <span>Account</span>
                <span>Init Mode</span>
                <span>Init Value</span>
                <span className="text-right">x</span>
              </div>
              {accounts.map((a) => (
                <div
                  key={a.name}
                  className="grid grid-cols-[160px_120px_100px_32px] gap-2 items-center px-2 py-1.5 border-b border-border/70"
                >
                  <span className="font-medium text-foreground" style={MONO}>{a.name}</span>
                  <FormSelect
                    value={a.initialMode}
                    onChange={(e) => {
                      syncAccountField(workspace, a.name, "INITIAL_MODE", e.target.value);
                      refresh();
                    }}
                  >
                    <option value="PCT_STACK">% bond stack</option>
                    <option value="FIXED_DOLLAR">$ amount</option>
                  </FormSelect>
                  <input
                    type="number"
                    value={a.initialAmt}
                    step={a.initialMode === "FIXED_DOLLAR" ? 1 : 0.01}
                    onChange={(e) => {
                      const v = parseFloat(e.target.value) || 0;
                      syncAccountField(workspace, a.name, "INITIAL_AMT", v);
                      refresh();
                    }}
                    className="w-full px-1.5 py-1 bg-input-background border border-border rounded text-foreground"
                    style={MONO}
                  />
                  <span className="text-muted-foreground text-right">{a.blockIds.length}x</span>
                </div>
              ))}
            </div>
          </div>
        </SectionCard>
      )}

      {triggers.length > 0 && (
        <SectionCard title="Triggers">
          <div className="overflow-x-auto">
            <div className="min-w-[420px]">
              <div className="grid grid-cols-[120px_140px_100px_32px] gap-2 px-2 py-1 text-xs text-muted-foreground uppercase tracking-wider border-b border-border">
                <span>Name</span>
                <span>Metric</span>
                <span>Threshold</span>
                <span className="text-right">x</span>
              </div>
              {triggers.map((t) => (
                <div
                  key={t.name}
                  className="grid grid-cols-[120px_140px_100px_32px] gap-2 items-center px-2 py-1.5 border-b border-border/70"
                >
                  <span className="font-medium text-foreground" style={MONO}>{t.name}</span>
                  <FormSelect
                    value={t.metric}
                    onChange={(e) => {
                      syncBlockField(
                        workspace,
                        "trigger_wrapper",
                        (block) => block.getFieldValue("TRIGGER_NAME") === t.name,
                        "METRIC",
                        e.target.value,
                      );
                      refresh();
                    }}
                  >
                    <option value="CUM_LOSS">CUM_LOSS</option>
                    <option value="CUM_DEFAULT">CUM_DEFAULT</option>
                    <option value="OC_RATIO">OC_RATIO</option>
                    <option value="IC_RATIO">IC_RATIO</option>
                    <option value="DELINQUENCY">DELINQUENCY</option>
                    <option value="CUSTOM">CUSTOM</option>
                  </FormSelect>
                  <input
                    type="number"
                    value={t.threshold}
                    step={0.001}
                    onChange={(e) => {
                      syncBlockField(
                        workspace,
                        "trigger_wrapper",
                        (block) => block.getFieldValue("TRIGGER_NAME") === t.name,
                        "THRESHOLD",
                        Number(e.target.value) || 0,
                      );
                      refresh();
                    }}
                    className="w-full px-1.5 py-1 bg-input-background border border-border rounded text-foreground"
                    style={MONO}
                  />
                  <span className="text-muted-foreground text-right">{t.blockIds.length}x</span>
                </div>
              ))}
            </div>
          </div>
        </SectionCard>
      )}

      {residuals.length > 0 && (
        <SectionCard title="Residuals">
          <EntityCounterSection
            title="Residual targets"
            compact
            rows={residuals.map((r) => ({ name: r.name, count: r.blockIds.length }))}
          />
        </SectionCard>
      )}

      {splits.length > 0 && (
        <SectionCard title="Split Accounts">
          <EntityCounterSection
            title="Split rules"
            compact
            rows={splits.map((s) => ({ name: `${s.source} -> ${s.out1}/${s.out2}`, count: s.blockIds.length }))}
          />
        </SectionCard>
      )}

      {bonds.length === 0
        && accounts.length === 0
        && residuals.length === 0
        && triggers.length === 0
        && fees.length === 0
        && splits.length === 0 && (
        <SectionCard title="Properties">
          <div className="text-muted-foreground italic py-4 text-center">
            Add bond or account targets to pay rules to see properties here
          </div>
        </SectionCard>
      )}
    </div>
  );
}

function EntityCounterSection({
  title,
  compact,
  rows,
}: {
  title: string;
  compact?: boolean;
  rows: Array<{ name: string; count: number }>;
}) {
  return (
    <div className={compact ? "" : "mt-1"}>
      <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1">{title}</div>
      {rows.map((row) => (
        <div key={row.name} className="flex items-center gap-2 py-1.5 border-b border-border/70">
          <span className="text-foreground" style={MONO}>{row.name}</span>
          <span className="ml-auto text-muted-foreground">{row.count}x</span>
        </div>
      ))}
    </div>
  );
}

function SectionCard({
  title,
  tooltipText,
  children,
}: {
  title: string;
  tooltipText?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-md border border-border bg-background/30">
      <div className="px-3 py-2 border-b border-border">
        <div className="flex items-center gap-1.5">
          <h3 className="text-xs font-medium tracking-wide uppercase text-muted-foreground">{title}</h3>
          {tooltipText && (
            <span className="relative inline-flex items-center group">
              <span
                className="inline-flex items-center text-muted-foreground/80 hover:text-foreground"
                aria-label={`${title} info`}
              >
                <Info className="h-3.5 w-3.5" />
              </span>
              <span
                role="tooltip"
                className="pointer-events-none absolute left-full top-1/2 z-20 ml-2 w-[460px] max-w-[70vw] -translate-y-1/2 rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-[12px] leading-5 font-sans normal-case tracking-normal text-slate-50 opacity-0 shadow-xl transition-opacity duration-150 group-hover:opacity-100"
              >
                {tooltipText}
              </span>
            </span>
          )}
        </div>
      </div>
      <div className="p-2">{children}</div>
    </section>
  );
}
