import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

import type { DealDefinitionIR } from "../ir-types";
import { useDealStore } from "./useDealStore";

type DealState = DealDefinitionIR;

type CompileModule = {
  compileToIR: (working_tree: DealState) => string;
};

const THIS_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(THIS_DIR, "../../../../../../..");

const FIXTURES_UNDER_TEST = [
  "fnr_2006_018",
  "ginniemae_2025_203",
  "verus_2024_9",
  "cc_series_test",
  "ford_2024_c",
] as const;

async function loadCompileModule(): Promise<CompileModule> {
  const mod = (await import("./compile")) as Partial<CompileModule>;
  expect(typeof mod.compileToIR).toBe("function");
  return mod as CompileModule;
}

function fixtureDirectory(name: string): string {
  return resolve(REPO_ROOT, "tests", "fixtures", name);
}

function fixturePath(name: string, fileName: string): string {
  return resolve(fixtureDirectory(name), fileName);
}

function shouldIncludeFixture(name: string): boolean {
  const hasBuilder = existsSync(fixturePath(name, "deal_definition.py"));
  const hasDealJson = existsSync(fixturePath(name, "deal.json"));
  return hasBuilder || hasDealJson;
}

function loadThroughStore(dealPayload: DealState): DealState {
  useDealStore.setState(useDealStore.getInitialState(), true);
  const activeSessionId = useDealStore.getState().activeSessionId;
  useDealStore.setState((state) => ({
    sessions: {
      ...state.sessions,
      [activeSessionId]: {
        ...state.sessions[activeSessionId],
        working_tree: dealPayload,
      },
    },
  }));
  return useDealStore.getState().sessions[activeSessionId].working_tree;
}

describe("sds-3 canonical roundtrip", () => {
  test("test_canonical_post_migration_round_trip_byte_identity_for_every_fixture", async () => {
    const { compileToIR } = await loadCompileModule();
    const fixtureNames = FIXTURES_UNDER_TEST.filter(shouldIncludeFixture);
    expect(fixtureNames.length).toBeGreaterThan(0);

    for (const fixtureName of fixtureNames) {
      const dealJsonPath = fixturePath(fixtureName, "deal.json");
      const canonicalPath = fixturePath(fixtureName, "deal.canonical.json");

      expect(existsSync(dealJsonPath)).toBe(true);
      expect(existsSync(canonicalPath)).toBe(true);

      const workingTree = loadThroughStore(
        JSON.parse(readFileSync(dealJsonPath, "utf-8")) as DealState,
      );
      const compiled = compileToIR(workingTree);
      const expectedCanonical = readFileSync(canonicalPath, "utf-8");
      expect(compiled).toBe(expectedCanonical);
    }
  });

  test("test_second_compile_is_byte_identical_idempotency", async () => {
    const { compileToIR } = await loadCompileModule();
    const fixtureNames = FIXTURES_UNDER_TEST.filter(shouldIncludeFixture);
    expect(fixtureNames.length).toBeGreaterThan(0);

    for (const fixtureName of fixtureNames) {
      const dealJsonPath = fixturePath(fixtureName, "deal.json");
      expect(existsSync(dealJsonPath)).toBe(true);

      const workingTree = loadThroughStore(
        JSON.parse(readFileSync(dealJsonPath, "utf-8")) as DealState,
      );
      const firstCompile = compileToIR(workingTree);
      const secondCompile = compileToIR(workingTree);
      expect(secondCompile).toBe(firstCompile);
    }
  });
});
