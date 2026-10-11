import { fireEvent, render, screen, within } from "@testing-library/react";
import type { UseQueryResult } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import type { PublicFilamentPool } from "./publicApi";
import { initialForm, PrintDetailsForm } from "./PublicPrintRequestForm";

describe("PrintDetailsForm", () => {
  it("updates material and colour when a spool is selected", () => {
    const updateField = vi.fn();
    render(<PrintDetailsForm form={{ ...initialForm, material: "PLA", color: "" }}
      updateField={updateField} poolsQuery={{ data: [{ id: 4, material: "PETG", color: "Black" }], isSuccess: true } as unknown as UseQueryResult<PublicFilamentPool[], Error>}
      modelFiles={[]} setModelFiles={vi.fn()} screenshotFiles={[]} setScreenshotFiles={vi.fn()}
      submitPending={false} uploadProgress="" website="" onWebsiteChange={vi.fn()} onSubmit={vi.fn()} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Filament / material" }), { target: { value: "4" } });
    expect(updateField.mock.calls).toEqual([["consumablePoolId", "4"], ["material", "PETG"], ["color", "Black"]]);
  });
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

  it("offers only the selected material's colours and clears the old colour and spool", () => {
    const updateField = vi.fn();
    render(<PrintDetailsForm
      form={{ ...initialForm, material: "PETG", color: "Black", consumablePoolId: "4" }}
      catalogue={{ materials: [
        { id: 1, name: "PETG", colours: ["Black"] },
        { id: 2, name: "PLA", colours: ["Blue"] },
      ], intake_schema: {} }}
      updateField={updateField}
      poolsQuery={{ data: [], isSuccess: true } as unknown as UseQueryResult<PublicFilamentPool[], Error>}
      modelFiles={[]} setModelFiles={vi.fn()} screenshotFiles={[]} setScreenshotFiles={vi.fn()}
      submitPending={false} uploadProgress="" website="" onWebsiteChange={vi.fn()} onSubmit={vi.fn()}
    />);
    const colours = within(screen.getByRole("combobox", { name: "Colour" }));
    expect(colours.getByRole("option", { name: "Black" })).toBeVisible();
    expect(colours.queryByRole("option", { name: "Blue" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Material" }), { target: { value: "PLA" } });
    expect(updateField.mock.calls).toEqual([["material", "PLA"], ["color", ""], ["consumablePoolId", ""]]);
  });
});
