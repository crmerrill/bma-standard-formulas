import type { Page, Route } from "@playwright/test";
import {
  makeBondCashflowRows,
  runListFixture,
  structuredArtifactsFixture,
} from "./fixtures";

function json(route: Route, payload: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(payload),
  });
}

export async function mountApiMocks(page: Page) {
  await page.route("**/api/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;

    if (path === "/api/runs-list") {
      return json(route, runListFixture);
    }

    if (path === "/api/uploads") {
      return json(route, { items: [] });
    }

    if (path === "/api/deals/pools") {
      return json(route, { items: [] });
    }

    if (path === "/api/runs/run_struct_001/artifacts") {
      return json(route, structuredArtifactsFixture);
    }

    if (path === "/api/runs/run_struct_001/preview/base_case_bond_cashflows") {
      const rows = makeBondCashflowRows(1200);
      return json(route, {
        section: "base_case_bond_cashflows",
        columns: [
          "period",
          "tranche_id",
          "total_principal",
          "interest_paid",
          "writedown",
          "end_balance",
          "interest_shortfall",
        ],
        rows,
        row_count: rows.length,
        truncated: false,
      });
    }

    if (path === "/api/deals/deal_abc") {
      return json(route, {
        deal_id: "deal_abc",
        deal_name: "Prime 2026-1",
        schema_version: "v1",
        saved_at: "2026-05-02T10:00:00Z",
        ir: {
          bonds: [
            { name: "A1", kind: "CASH_PAY" },
            { name: "B1", kind: "CASH_PAY" },
            { name: "R", kind: "RESIDUAL" },
          ],
        },
      });
    }

    // Avoid accidental backend dependency in e2e harness.
    return json(route, { detail: `Unhandled mock path: ${path}` }, 501);
  });
}

export async function setSessionState(page: Page, state: Record<string, unknown>) {
  await page.addInitScript((seed) => {
    window.sessionStorage.setItem("bma_cfengine_session", JSON.stringify(seed));
  }, state);
}
