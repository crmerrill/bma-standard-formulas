/**
 * rcf-2-fragmentation-detector: TS parity tests (T1).
 *
 * This suite is intentionally RED until canonicalizationValidators.ts is added.
 */

import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { describe, it, expect } from "vitest";
import { getDiagnosticValidator } from "./diagnosticRegistry";
import "./canonicalizationValidators";

type CatalogRow = {
  code: string;
  severity: string;
  pathSchema: string;
  message: string;
  owner: string;
  quickFix: string;
  validatorFileLine: string;
};

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "../../../../../../");
const CATALOG_PATH = path.resolve(
  __dirname,
  "../../../../../../docs/architecture/diagnostic_catalog.md",
);

function baseRule(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    rule_id: "r1",
    rule_type: "PAY_INTEREST",
    order: 0,
    from_sources: ["CASH"],
    to_targets: ["CLASS_A"],
    payment_style: "SEQUENTIAL",
    cap_mode: null,
    condition_trigger: null,
    condition_invert: false,
    condition_expr: null,
    group_id: null,
    coverage_mode: "NORMAL",
    allow_negative_source: false,
    max_amount_fixed: null,
    max_amount_expr: null,
    target_weights: null,
    ...overrides,
  };
}

function parseCatalogRow(code: string): CatalogRow | undefined {
  const markdown = fs.readFileSync(CATALOG_PATH, "utf-8");
  const row = markdown
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find((line) => line.startsWith(`| ${code} |`));

  if (!row) {
    return undefined;
  }

  const cells = row
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());

  if (cells.length !== 7) {
    throw new Error(`Unexpected diagnostic catalog row format: ${row}`);
  }

  return {
    code: cells[0],
    severity: cells[1],
    pathSchema: cells[2],
    message: cells[3],
    owner: cells[4],
    quickFix: cells[5],
    validatorFileLine: cells[6],
  };
}

type PythonDiagnostic = {
  code: string;
  path: string;
  payload: Record<string, unknown>;
  fix?: { action_id: string; params: Record<string, unknown> } | null;
};

function runPythonValidator(code: string, deal: unknown): PythonDiagnostic[] {
  const pyScript = `
import importlib
import json
import sys
from bma_standard_formulas.diagnostics import iter_diagnostics
import bma_standard_formulas.diagnostics.canonicalization_validators  # noqa: F401

code = sys.argv[1]
deal = json.loads(sys.stdin.read())
descriptor = next((d for d in iter_diagnostics() if d.code == code), None)
if descriptor is None:
    raise SystemExit(f"missing validator: {code}")

module_name, func_name = descriptor.validator_qualname.rsplit(".", 1)
fn = getattr(importlib.import_module(module_name), func_name)
results = fn(deal)
print(json.dumps([r.model_dump(mode="json") for r in results], sort_keys=True))
`.trim();

  const pythonPath = process.env.PYTHONPATH
    ? `${REPO_ROOT}/src${path.delimiter}${process.env.PYTHONPATH}`
    : `${REPO_ROOT}/src`;
  const completed = spawnSync("python", ["-c", pyScript, code], {
    cwd: REPO_ROOT,
    input: JSON.stringify(deal),
    encoding: "utf-8",
    env: {
      ...process.env,
      PYTHONPATH: pythonPath,
    },
  });
  expect(completed.status).toBe(0);

  return JSON.parse(completed.stdout) as PythonDiagnostic[];
}

describe("rcf-2 fragmentation detector parity", () => {
  it("test_fragmentation_detector_emits_diagnostic_for_consecutive_run", () => {
    const descriptor = getDiagnosticValidator("RULE_FRAGMENTATION_CONSOLIDATABLE");
    expect(descriptor).toBeDefined();

    const deal = {
      waterfall_rules: [
        baseRule({ rule_id: "r1", order: 0, to_targets: ["CLASS_A"] }),
        baseRule({ rule_id: "r2", order: 1, to_targets: ["CLASS_B"] }),
        baseRule({ rule_id: "r3", order: 2, to_targets: ["CLASS_C"] }),
      ],
    };
    const diagnostics = descriptor!.fn(deal);

    expect(diagnostics).toHaveLength(1);
    const diagnostic = diagnostics[0];
    expect(diagnostic.code).toBe("RULE_FRAGMENTATION_CONSOLIDATABLE");
    expect(diagnostic.severity).toBe("warning");
    expect(diagnostic.path).toBe("deal.waterfall_rules[0..2]");
    expect(diagnostic.payload).toEqual({
      start_index: 0,
      end_index: 2,
      rule_ids: ["r1", "r2", "r3"],
      source: "CASH",
      target_count: 3,
    });
    expect(diagnostic.fix).toEqual({
      action_id: "canonicalize_consolidate_rule_run",
      params: { start_index: 0, end_index: 2 },
    });
  });

  it("test_fragmentation_detector_ignores_non_consolidatable_rules", () => {
    const descriptor = getDiagnosticValidator("RULE_FRAGMENTATION_CONSOLIDATABLE");
    expect(descriptor).toBeDefined();

    const deal = {
      waterfall_rules: [
        baseRule({ rule_id: "r1", order: 0, payment_style: "SEQUENTIAL" }),
        baseRule({ rule_id: "r2", order: 1, payment_style: "PRO_RATA" }),
      ],
    };
    const diagnostics = descriptor!.fn(deal);
    expect(diagnostics).toEqual([]);
  });

  it("test_fragmentation_detector_payload_matches_pinned_schema", () => {
    const descriptor = getDiagnosticValidator("RULE_FRAGMENTATION_CONSOLIDATABLE");
    expect(descriptor).toBeDefined();

    const deal = {
      waterfall_rules: [
        baseRule({ rule_id: "r1", order: 0, to_targets: ["CLASS_A"] }),
        baseRule({ rule_id: "r2", order: 1, to_targets: ["CLASS_B"] }),
      ],
    };
    const diagnostics = descriptor!.fn(deal);

    expect(diagnostics).toHaveLength(1);
    const diagnostic = diagnostics[0];
    expect(diagnostic.path).toMatch(/^deal\.waterfall_rules\[\d+\.\.\d+\]$/);
    expect(typeof diagnostic.payload.start_index).toBe("number");
    expect(typeof diagnostic.payload.end_index).toBe("number");
    expect(Array.isArray(diagnostic.payload.rule_ids)).toBe(true);
    expect(
      (diagnostic.payload.rule_ids as unknown[]).every((ruleId) => typeof ruleId === "string"),
    ).toBe(true);
    expect(typeof diagnostic.payload.source).toBe("string");
    expect(typeof diagnostic.payload.target_count).toBe("number");
    expect(diagnostic.fix?.action_id).toBe("canonicalize_consolidate_rule_run");
    expect(typeof diagnostic.fix?.params.start_index).toBe("number");
    expect(typeof diagnostic.fix?.params.end_index).toBe("number");
  });

  it("test_catalog_row_present_for_rule_fragmentation_consolidatable", () => {
    const row = parseCatalogRow("RULE_FRAGMENTATION_CONSOLIDATABLE");
    expect(row).toBeDefined();
    expect(row?.code).toBe("RULE_FRAGMENTATION_CONSOLIDATABLE");
    expect(row?.severity).toBe("warning");
    expect(row?.pathSchema).toBe("deal.waterfall_rules[start_index..end_index]");
    expect(row?.message).toBe(
      "Rules {start_index} through {end_index} can be consolidated into one multi-target rule.",
    );
    expect(row?.owner).toBe("both");
    expect(row?.quickFix).toBe("canonicalize_consolidate_rule_run");
    expect(row?.validatorFileLine.split(":", 1)[0]).toBe("canonicalization_validators.py");
  });
});

describe("rcf-4 interleaved detector parity", () => {
  it("test_interleaved_detector_emits_info_diagnostic", () => {
    const descriptor = getDiagnosticValidator("INTERLEAVED_RULES_FACTORABLE");
    expect(descriptor).toBeDefined();

    const deal = {
      waterfall_rules: [
        baseRule({ rule_id: "x0", order: 0, from_sources: ["RESERVE"], to_targets: ["CLASS_Z"] }),
        baseRule({ rule_id: "a", order: 1, from_sources: ["CASH"], to_targets: ["CLASS_A"] }),
        baseRule({
          rule_id: "m",
          order: 2,
          from_sources: ["CASH"],
          to_targets: ["CLASS_M"],
          payment_style: "PRO_RATA",
        }),
        baseRule({ rule_id: "b", order: 3, from_sources: ["CASH"], to_targets: ["CLASS_B"] }),
        baseRule({ rule_id: "x4", order: 4, from_sources: ["RESERVE"], to_targets: ["CLASS_Q"] }),
        baseRule({ rule_id: "c", order: 5, from_sources: ["CASH"], to_targets: ["CLASS_C"] }),
      ],
    };
    const diagnostics = descriptor!.fn(deal);

    expect(diagnostics).toHaveLength(1);
    const diagnostic = diagnostics[0];
    expect(diagnostic.code).toBe("INTERLEAVED_RULES_FACTORABLE");
    expect(diagnostic.severity).toBe("info");
    expect(diagnostic.path).toBe("deal.waterfall_rules[1,3,5]");
    expect(Object.prototype.hasOwnProperty.call(diagnostic, "fix")).toBe(false);
  });

  it("test_interleaved_detector_fix_is_null_never_autofix", () => {
    const descriptor = getDiagnosticValidator("INTERLEAVED_RULES_FACTORABLE");
    expect(descriptor).toBeDefined();

    const deal = {
      waterfall_rules: [
        baseRule({ rule_id: "a", order: 0, from_sources: ["CASH"], to_targets: ["CLASS_A"] }),
        baseRule({
          rule_id: "m",
          order: 1,
          from_sources: ["CASH"],
          to_targets: ["CLASS_M"],
          payment_style: "PRO_RATA",
        }),
        baseRule({ rule_id: "b", order: 2, from_sources: ["CASH"], to_targets: ["CLASS_B"] }),
      ],
    };
    const diagnostics = descriptor!.fn(deal);

    expect(diagnostics).toHaveLength(1);
    const diagnostic = diagnostics[0];
    expect(Object.prototype.hasOwnProperty.call(diagnostic, "fix")).toBe(false);
    const serialized = JSON.parse(JSON.stringify(diagnostic)) as Record<string, unknown>;
    expect(Object.prototype.hasOwnProperty.call(serialized, "fix")).toBe(false);
  });

  it("test_interleaved_detector_path_uses_comma_separated_indices", () => {
    const descriptor = getDiagnosticValidator("INTERLEAVED_RULES_FACTORABLE");
    expect(descriptor).toBeDefined();

    const deal = {
      waterfall_rules: [
        baseRule({ rule_id: "x0", order: 0, from_sources: ["RESERVE"], to_targets: ["CLASS_0"] }),
        baseRule({ rule_id: "x1", order: 1, from_sources: ["RESERVE"], to_targets: ["CLASS_1"] }),
        baseRule({ rule_id: "x2", order: 2, from_sources: ["RESERVE"], to_targets: ["CLASS_2"] }),
        baseRule({ rule_id: "x3", order: 3, from_sources: ["RESERVE"], to_targets: ["CLASS_3"] }),
        baseRule({ rule_id: "a", order: 4, from_sources: ["CASH"], to_targets: ["CLASS_A"] }),
        baseRule({
          rule_id: "m",
          order: 5,
          from_sources: ["CASH"],
          to_targets: ["CLASS_M"],
          payment_style: "PRO_RATA",
        }),
        baseRule({ rule_id: "x6", order: 6, from_sources: ["RESERVE"], to_targets: ["CLASS_6"] }),
        baseRule({ rule_id: "b", order: 7, from_sources: ["CASH"], to_targets: ["CLASS_B"] }),
        baseRule({ rule_id: "x8", order: 8, from_sources: ["RESERVE"], to_targets: ["CLASS_8"] }),
        baseRule({ rule_id: "c", order: 9, from_sources: ["CASH"], to_targets: ["CLASS_C"] }),
      ],
    };
    const diagnostics = descriptor!.fn(deal);

    expect(diagnostics).toHaveLength(1);
    expect(diagnostics[0].path).toBe("deal.waterfall_rules[4,7,9]");
  });

  it("test_interleaved_detector_groups_transitively_with_internal_mutator", () => {
    const descriptor = getDiagnosticValidator("INTERLEAVED_RULES_FACTORABLE");
    expect(descriptor).toBeDefined();

    const deal = {
      waterfall_rules: [
        baseRule({ rule_id: "x0", order: 0, from_sources: ["RESERVE"], to_targets: ["CLASS_0"] }),
        baseRule({ rule_id: "a", order: 1, from_sources: ["CASH"], to_targets: ["CLASS_A"] }),
        baseRule({
          rule_id: "m",
          order: 2,
          from_sources: ["CASH"],
          to_targets: ["CLASS_M"],
          payment_style: "PRO_RATA",
        }),
        baseRule({ rule_id: "b", order: 3, from_sources: ["CASH"], to_targets: ["CLASS_B"] }),
        baseRule({ rule_id: "c", order: 4, from_sources: ["CASH"], to_targets: ["CLASS_C"] }),
      ],
    };
    const diagnostics = descriptor!.fn(deal);

    expect(diagnostics).toHaveLength(1);
    expect(diagnostics[0].path).toBe("deal.waterfall_rules[1,3,4]");
  });

  it("test_interleaved_detector_ignores_rules_without_mutator", () => {
    const descriptor = getDiagnosticValidator("INTERLEAVED_RULES_FACTORABLE");
    expect(descriptor).toBeDefined();

    const contiguous = {
      waterfall_rules: [
        baseRule({ rule_id: "a", order: 0, from_sources: ["CASH"], to_targets: ["CLASS_A"] }),
        baseRule({ rule_id: "b", order: 1, from_sources: ["CASH"], to_targets: ["CLASS_B"] }),
      ],
    };
    const separatedNonMutating = {
      waterfall_rules: [
        baseRule({ rule_id: "a", order: 0, from_sources: ["CASH"], to_targets: ["CLASS_A"] }),
        baseRule({
          rule_id: "x",
          order: 1,
          from_sources: ["RESERVE"],
          to_targets: ["CLASS_X"],
          payment_style: "PRO_RATA",
        }),
        baseRule({ rule_id: "b", order: 2, from_sources: ["CASH"], to_targets: ["CLASS_B"] }),
      ],
    };

    expect(descriptor!.fn(contiguous)).toEqual([]);
    expect(descriptor!.fn(separatedNonMutating)).toEqual([]);
  });

  it("test_interleaved_detector_python_ts_emit_byte_identical_payload", () => {
    const descriptor = getDiagnosticValidator("INTERLEAVED_RULES_FACTORABLE");
    expect(descriptor).toBeDefined();

    const deal = {
      waterfall_rules: [
        baseRule({ rule_id: "x0", order: 0, from_sources: ["RESERVE"], to_targets: ["CLASS_Z"] }),
        baseRule({ rule_id: "a", order: 1, from_sources: ["CASH"], to_targets: ["CLASS_A"] }),
        baseRule({
          rule_id: "m",
          order: 2,
          from_sources: ["CASH"],
          to_targets: ["CLASS_M"],
          payment_style: "PRO_RATA",
        }),
        baseRule({ rule_id: "b", order: 3, from_sources: ["CASH"], to_targets: ["CLASS_B"] }),
        baseRule({ rule_id: "x4", order: 4, from_sources: ["RESERVE"], to_targets: ["CLASS_Q"] }),
        baseRule({ rule_id: "c", order: 5, from_sources: ["CASH"], to_targets: ["CLASS_C"] }),
      ],
    };

    const tsDiagnostics = descriptor!.fn(deal);
    const pyDiagnostics = runPythonValidator("INTERLEAVED_RULES_FACTORABLE", deal);
    expect(tsDiagnostics).toHaveLength(pyDiagnostics.length);

    const tsTriples = tsDiagnostics.map((d) => ({
      code: d.code,
      path: d.path,
      payload: d.payload,
    }));
    const pyTriples = pyDiagnostics.map((d) => ({
      code: d.code,
      path: d.path,
      payload: d.payload,
    }));
    expect(tsTriples).toEqual(pyTriples);

    const tsHasFixField = tsDiagnostics.map((d) => Object.prototype.hasOwnProperty.call(d, "fix"));
    const pyFixIsNone = pyDiagnostics.map((d) => Object.prototype.hasOwnProperty.call(d, "fix") && d.fix === null);
    expect(tsHasFixField).toEqual(pyFixIsNone.map(() => false));
    expect(pyFixIsNone).toEqual(tsHasFixField.map(() => true));
  });
});
