import { expect } from "vitest";
import { axe } from "vitest-axe";

export async function expectNoA11yViolations(container: HTMLElement) {
  const results = await axe(container, {
    rules: {
      // color contrast in jsdom is unreliable; enforce in Playwright a11y instead.
      "color-contrast": { enabled: false },
    },
  });
  expect(results.violations, JSON.stringify(results.violations, null, 2)).toHaveLength(0);
}
