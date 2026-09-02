import { describe, expect, it } from "vitest";

import { StructuredApiError } from "../../lib/api";
import { evidenceErrorText } from "./evidenceUi";


describe("evidenceErrorText", () => {
  it("turns terminal retention responses into an explicit expired-photo message", () => {
    const result = evidenceErrorText(new StructuredApiError(410, {
      code: "evidence_expired",
      object_expired_at: "2026-09-02T10:00:00Z",
    }));

    expect(result).toMatch(/^Photo expired on .+ under retention policy\.$/);
  });

  it("preserves ordinary evidence failures", () => {
    expect(evidenceErrorText(new Error("Storage unavailable"))).toBe(
      "Storage unavailable",
    );
  });
});
