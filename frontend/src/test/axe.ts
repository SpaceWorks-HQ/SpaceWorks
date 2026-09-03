import axe, { type AxeResults, type RunOptions } from "axe-core";

// WCAG 2.1 AA is the accessibility floor in docs/INVARIANTS.md. Panel tests call this on
// their rendered container so a regression fails the unit suite, not a later audit.
const RULES: RunOptions = {
  runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
  // jsdom has no layout engine, so colour-contrast cannot be computed here; Playwright
  // runs it against the real browser (frontend/e2e/a11y.spec.ts).
  rules: { "color-contrast": { enabled: false } },
};

export async function expectNoA11yViolations(container: Element): Promise<void> {
  const results: AxeResults = await axe.run(container, RULES);
  const violations = results.violations.map(
    (violation) =>
      `${violation.id} (${violation.impact}): ${violation.help}\n` +
      violation.nodes.map((node) => `  - ${node.target.join(" ")}`).join("\n"),
  );
  if (violations.length) {
    throw new Error(`Accessibility violations:\n${violations.join("\n")}`);
  }
}
