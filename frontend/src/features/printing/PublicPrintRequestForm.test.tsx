import { render, screen } from "@testing-library/react";
import type { UseQueryResult } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import type { PublicFilamentPool } from "./publicApi";
import { initialForm, PrintDetailsForm } from "./PublicPrintRequestForm";

describe("PrintDetailsForm", () => {
  it("shows an actionable empty state when no public filament can be selected", () => {
    const poolsQuery = {
      data: [],
      isSuccess: true,
      isLoading: false,
      isError: false,
    } as unknown as UseQueryResult<PublicFilamentPool[], Error>;

    render(
      <PrintDetailsForm
        form={initialForm}
        updateField={vi.fn()}
        poolsQuery={poolsQuery}
        modelFiles={[]}
        setModelFiles={vi.fn()}
        screenshotFiles={[]}
        setScreenshotFiles={vi.fn()}
        submitPending={false}
        uploadProgress=""
        website=""
        onWebsiteChange={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByRole("heading", { name: "No filament currently available" })).toBeVisible();
    expect(screen.getByText(/still submit without a preference/i)).toBeVisible();
    expect(screen.queryByRole("combobox", { name: "Filament / material" })).not.toBeInTheDocument();
  });
});
