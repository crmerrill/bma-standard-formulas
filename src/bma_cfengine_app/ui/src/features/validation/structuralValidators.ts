/**
 * Structural validators for deal payloads — owner='both' (Python + TS parity).
 *
 * These validators mirror the Python implementations in
 * src/bma_standard_formulas/diagnostics/structural_validators.py and must
 * produce identical (code, path) output for the same input deal payload.
 *
 * Adding a validator here requires:
 *   1. A matching @diagnostic_code decorator in the Python structural_validators module.
 *   2. A new row in docs/architecture/diagnostic_catalog.md.
 *   3. Verifying python -m bma_standard_formulas.diagnostics.check exits 0.
 */

import { registerDiagnosticValidator } from "./diagnosticRegistry";
import type { DiagnosticPayload } from "../deals/store/diagnostics-types";

registerDiagnosticValidator({
  code: "BOND_NAME_EMPTY",
  severity: "error",
  pathSchema: "deal.bonds[*].name",
  owner: "both",
  fn(deal: unknown): DiagnosticPayload[] {
    const d = deal as Record<string, unknown>;
    const bonds = Array.isArray(d.bonds) ? d.bonds : [];
    const results: DiagnosticPayload[] = [];
    for (let i = 0; i < bonds.length; i++) {
      const bond = bonds[i] as Record<string, unknown>;
      const name = typeof bond.name === "string" ? bond.name : "";
      if (!name.trim()) {
        results.push({
          code: "BOND_NAME_EMPTY",
          severity: "error",
          path: `deal.bonds[${i}].name`,
          message: `Bond at index ${i} has an empty or missing name.`,
          payload: { index: i },
        });
      }
    }
    return results;
  },
});

registerDiagnosticValidator({
  code: "BOND_NAME_DUPLICATE",
  severity: "error",
  pathSchema: "deal.bonds[*].name",
  owner: "both",
  fn(deal: unknown): DiagnosticPayload[] {
    const d = deal as Record<string, unknown>;
    const bonds = Array.isArray(d.bonds) ? d.bonds : [];
    const results: DiagnosticPayload[] = [];
    const seen = new Map<string, number>();
    for (let i = 0; i < bonds.length; i++) {
      const bond = bonds[i] as Record<string, unknown>;
      const name = typeof bond.name === "string" ? bond.name : "";
      if (!name.trim()) continue;
      if (seen.has(name)) {
        results.push({
          code: "BOND_NAME_DUPLICATE",
          severity: "error",
          path: `deal.bonds[${i}].name`,
          message: `Bond '${name}' at index ${i} duplicates bond at index ${seen.get(name)}.`,
          payload: { index: i, first_index: seen.get(name), name },
          // ve-5 QuickFix: manual_resolve_* signals that user judgment is needed
          // (we don't auto-rename without context). Phase 2 Problems Panel
          // renders the hint and surfaces a rename UI.
          fix: {
            action_id: "manual_resolve_duplicate_bond_name",
            params: {
              duplicate_index: i,
              first_index: seen.get(name),
              name,
              hint: `Rename one of the bonds named '${name}'.`,
            },
          },
        });
      } else {
        seen.set(name, i);
      }
    }
    return results;
  },
});

const BUILTIN_STREAMS = new Set(["CASH", "ACT_INT", "ACT_PRIN", "LOSS"]);

function buildValidReferences(
  deal: Record<string, unknown>,
): { validSources: Set<string>; validTargets: Set<string> } {
  const bonds = Array.isArray(deal.bonds) ? deal.bonds : [];
  const accounts = Array.isArray(deal.accounts) ? deal.accounts : [];
  const fees = Array.isArray(deal.fees) ? deal.fees : [];
  const collateralGroups = Array.isArray(deal.collateral_groups)
    ? deal.collateral_groups
    : [];

  const bondNames = new Set(
    bonds
      .map((b: Record<string, unknown>) => b.name as string)
      .filter(Boolean),
  );
  const accountNames = new Set(
    accounts
      .map((a: Record<string, unknown>) => a.name as string)
      .filter(Boolean),
  );
  const feeNames = new Set(
    fees
      .map((f: Record<string, unknown>) => f.name as string)
      .filter(Boolean),
  );
  const groupIds = new Set(
    collateralGroups
      .map((g: Record<string, unknown>) => g.group_id as string)
      .filter(Boolean),
  );

  const sourceFormulaNames = new Set<string>();
  const dealKnobs = deal.deal_knobs as Record<string, unknown> | undefined;
  if (dealKnobs && typeof dealKnobs === "object") {
    const rawSf = dealKnobs.source_formulas;
    if (rawSf && typeof rawSf === "object" && !Array.isArray(rawSf)) {
      for (const k of Object.keys(rawSf as Record<string, unknown>)) {
        sourceFormulaNames.add(k);
      }
    }
  }

  const groupStreams = new Set<string>();
  for (const gid of groupIds) {
    for (const suffix of ["CASH", "ACT_INT", "ACT_PRIN", "LOSS"]) {
      groupStreams.add(`GROUP_${gid}_${suffix}`);
    }
  }

  const entityNames = new Set([...bondNames, ...accountNames, ...feeNames]);

  const splitStreams = new Set<string>();
  const rules = Array.isArray(deal.waterfall_rules)
    ? deal.waterfall_rules
    : [];
  const rulesSorted = [...rules].sort(
    (a: Record<string, unknown>, b: Record<string, unknown>) =>
      ((a.order as number) ?? 0) - ((b.order as number) ?? 0),
  );
  for (const rule of rulesSorted) {
    const r = rule as Record<string, unknown>;
    if (r.rule_type === "SPLIT_CASH") {
      const toTargets = Array.isArray(r.to_targets) ? r.to_targets : [];
      for (const tgt of toTargets) {
        const t = tgt as string;
        if (
          !entityNames.has(t) &&
          !BUILTIN_STREAMS.has(t) &&
          !sourceFormulaNames.has(t)
        ) {
          splitStreams.add(t);
        }
      }
    }
  }

  const allTargets = new Set([...entityNames, "CASH"]);
  const validSources = new Set([
    ...allTargets,
    ...BUILTIN_STREAMS,
    ...groupStreams,
    ...sourceFormulaNames,
    ...splitStreams,
  ]);
  const validTargets = new Set([
    ...allTargets,
    ...splitStreams,
    ...BUILTIN_STREAMS,
    ...groupStreams,
  ]);

  return { validSources, validTargets };
}

registerDiagnosticValidator({
  code: "REFERENCE_BROKEN",
  severity: "error",
  pathSchema: "deal.waterfall_rules[*].from_sources",
  owner: "both",
  fn(deal: unknown): DiagnosticPayload[] {
    const d = deal as Record<string, unknown>;
    const rules = Array.isArray(d.waterfall_rules) ? d.waterfall_rules : [];
    const { validSources, validTargets } = buildValidReferences(d);

    const results: DiagnosticPayload[] = [];
    for (let i = 0; i < rules.length; i++) {
      const rule = rules[i] as Record<string, unknown>;
      const fromSources = Array.isArray(rule.from_sources)
        ? rule.from_sources
        : [];
      const toTargets = Array.isArray(rule.to_targets) ? rule.to_targets : [];

      let hasBrokenSource = false;
      for (const src of fromSources) {
        if (!validSources.has(src as string)) {
          hasBrokenSource = true;
          break;
        }
      }
      if (hasBrokenSource) {
        results.push({
          code: "REFERENCE_BROKEN",
          severity: "error",
          path: `deal.waterfall_rules[${i}].from_sources`,
          message: `Rule '${rule.rule_id ?? ""}' references non-existent source(s).`,
          payload: { rule_index: i, rule_id: rule.rule_id ?? "" },
        });
      }

      let hasBrokenTarget = false;
      for (const tgt of toTargets) {
        if (!validTargets.has(tgt as string)) {
          hasBrokenTarget = true;
          break;
        }
      }
      if (hasBrokenTarget) {
        results.push({
          code: "REFERENCE_BROKEN",
          severity: "error",
          path: `deal.waterfall_rules[${i}].to_targets`,
          message: `Rule '${rule.rule_id ?? ""}' references non-existent target(s).`,
          payload: { rule_index: i, rule_id: rule.rule_id ?? "" },
        });
      }
    }
    return results;
  },
});

registerDiagnosticValidator({
  code: "MULTI_TARGET_WEIGHT_SUM_INVALID",
  severity: "error",
  pathSchema: "deal.waterfall_rules[*].target_weights",
  owner: "both",
  fn(deal: unknown): DiagnosticPayload[] {
    const d = deal as Record<string, unknown>;
    const rules = Array.isArray(d.waterfall_rules) ? d.waterfall_rules : [];
    const results: DiagnosticPayload[] = [];
    const epsilon = 1e-9;
    for (let i = 0; i < rules.length; i++) {
      const rule = rules[i] as Record<string, unknown>;
      const weights = rule.target_weights;
      if (!Array.isArray(weights) || weights.length === 0) continue;
      const total = (weights as number[]).reduce((a, b) => a + b, 0);
      if (Math.abs(total - 1.0) > epsilon) {
        results.push({
          code: "MULTI_TARGET_WEIGHT_SUM_INVALID",
          severity: "error",
          path: `deal.waterfall_rules[${i}].target_weights`,
          message: `Rule '${rule.rule_id ?? ""}' target_weights sum to ${total.toFixed(6)}, expected 1.0.`,
          payload: { rule_index: i, rule_id: rule.rule_id ?? "", sum: total },
        });
      }
    }
    return results;
  },
});

const PAC_TAC_KINDS = new Set(["PAC", "TAC"]);

registerDiagnosticValidator({
  code: "KIND_SCHEDULE_SOURCE_INCONSISTENT",
  severity: "error",
  pathSchema: "deal.bonds[*].kind",
  owner: "both",
  fn(deal: unknown): DiagnosticPayload[] {
    const d = deal as Record<string, unknown>;
    const bonds = Array.isArray(d.bonds) ? d.bonds : [];
    const results: DiagnosticPayload[] = [];
    for (let i = 0; i < bonds.length; i++) {
      const bond = bonds[i] as Record<string, unknown>;
      const kind = (bond.kind as string) ?? "CASH_PAY";
      const hasContract =
        Array.isArray(bond.schedule_contract) &&
        bond.schedule_contract.length > 0;
      const hasModel = bond.schedule_model_type != null;
      if (PAC_TAC_KINDS.has(kind)) {
        if (!hasContract && !hasModel) {
          results.push({
            code: "KIND_SCHEDULE_SOURCE_INCONSISTENT",
            severity: "error",
            path: `deal.bonds[${i}].kind`,
            message: `Bond '${bond.name ?? ""}' (kind=${kind}) requires schedule_contract or schedule_model_type.`,
            payload: { index: i, kind },
          });
        }
      } else {
        if (hasContract || hasModel) {
          results.push({
            code: "KIND_SCHEDULE_SOURCE_INCONSISTENT",
            severity: "error",
            path: `deal.bonds[${i}].kind`,
            message: `Bond '${bond.name ?? ""}' (kind=${kind}) must not have schedule_contract or schedule_model_type.`,
            payload: { index: i, kind },
          });
        }
      }
    }
    return results;
  },
});

registerDiagnosticValidator({
  code: "NLA_SUBORDINATION_INCONSISTENT",
  severity: "error",
  pathSchema: "deal.bonds[*].nla_starting_balance",
  owner: "both",
  fn(deal: unknown): DiagnosticPayload[] {
    const d = deal as Record<string, unknown>;
    const bonds = Array.isArray(d.bonds) ? d.bonds : [];
    const results: DiagnosticPayload[] = [];
    for (let i = 0; i < bonds.length; i++) {
      const bond = bonds[i] as Record<string, unknown>;
      const hasNla = bond.nla_starting_balance != null;
      const hasSub = bond.required_subordination_pct != null;
      if (hasNla !== hasSub) {
        results.push({
          code: "NLA_SUBORDINATION_INCONSISTENT",
          severity: "error",
          path: `deal.bonds[${i}].nla_starting_balance`,
          message: `Bond '${bond.name ?? ""}' has ${hasNla ? "nla_starting_balance" : "required_subordination_pct"} set but not ${hasNla ? "required_subordination_pct" : "nla_starting_balance"}.`,
          payload: { index: i, has_nla: hasNla, has_sub: hasSub },
        });
      }
    }
    return results;
  },
});

function extractGroupFromToken(token: string): string | null {
  for (const suffix of ["_CASH", "_ACT_INT", "_ACT_PRIN", "_LOSS"]) {
    if (token.startsWith("GROUP_") && token.endsWith(suffix)) {
      return token.slice("GROUP_".length, -suffix.length);
    }
  }
  return null;
}

registerDiagnosticValidator({
  code: "MULTI_GROUP_ROUTING_INVALID",
  severity: "error",
  pathSchema: "deal.waterfall_rules[*].from_sources",
  owner: "both",
  fn(deal: unknown): DiagnosticPayload[] {
    const d = deal as Record<string, unknown>;
    const collateralGroups = Array.isArray(d.collateral_groups)
      ? d.collateral_groups
      : [];
    const rules = Array.isArray(d.waterfall_rules) ? d.waterfall_rules : [];

    const groupIds = new Set(
      collateralGroups
        .map((g: Record<string, unknown>) => g.group_id as string)
        .filter(Boolean),
    );
    if (groupIds.size === 0) return [];

    const validGroupStreams = new Set<string>();
    for (const gid of groupIds) {
      for (const suffix of ["CASH", "ACT_INT", "ACT_PRIN", "LOSS"]) {
        validGroupStreams.add(`GROUP_${gid}_${suffix}`);
      }
    }

    const results: DiagnosticPayload[] = [];
    for (let i = 0; i < rules.length; i++) {
      const rule = rules[i] as Record<string, unknown>;
      const fromSources = Array.isArray(rule.from_sources)
        ? rule.from_sources
        : [];
      const toTargets = Array.isArray(rule.to_targets)
        ? rule.to_targets
        : [];

      let hasInvalidSource = false;
      for (const src of fromSources) {
        if (
          typeof src === "string" &&
          src.startsWith("GROUP_") &&
          !validGroupStreams.has(src)
        ) {
          hasInvalidSource = true;
          break;
        }
      }
      let hasInvalidTarget = false;
      for (const tgt of toTargets) {
        if (
          typeof tgt === "string" &&
          tgt.startsWith("GROUP_") &&
          !validGroupStreams.has(tgt)
        ) {
          hasInvalidTarget = true;
          break;
        }
      }

      if (hasInvalidSource || hasInvalidTarget) {
        results.push({
          code: "MULTI_GROUP_ROUTING_INVALID",
          severity: "error",
          path: `deal.waterfall_rules[${i}].from_sources`,
          message: `Rule '${rule.rule_id ?? ""}' references group-prefixed token not in declared collateral_groups.`,
          payload: { rule_index: i, rule_id: rule.rule_id ?? "" },
        });
        continue;
      }

      const ruleGroupId = rule.group_id as string | undefined;
      if (!ruleGroupId) continue;
      const allKeys = [
        ...fromSources.map((s: unknown) => s as string),
        ...toTargets.map((t: unknown) => t as string),
      ];
      const hasBare = allKeys.some((k) => BUILTIN_STREAMS.has(k));
      if (!hasBare) continue;
      for (const key of allKeys) {
        const otherGroup = extractGroupFromToken(key);
        if (otherGroup !== null && otherGroup !== ruleGroupId) {
          results.push({
            code: "MULTI_GROUP_ROUTING_INVALID",
            severity: "error",
            path: `deal.waterfall_rules[${i}].from_sources`,
            message: `Rule '${rule.rule_id ?? ""}' mixes bare collateral tokens (scoped to group_id='${ruleGroupId}') with explicit token '${key}' for a different group '${otherGroup}'.`,
            payload: { rule_index: i, rule_id: rule.rule_id ?? "" },
          });
          break;
        }
      }
    }
    return results;
  },
});
