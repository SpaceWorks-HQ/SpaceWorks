import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { DataTable } from "./DataTable";
import { useUrlListState } from "../../lib/useUrlListState";
import { expectNoA11yViolations } from "../../test/axe";

function Table() {
  const list = useUrlListState({ page: "1" });
  return <><DataTable listState={list} data={[{ id: 1, name: "Drill", count: 3 }]} columns={[{ key: "name", header: "Name" }, { key: "count", header: "Count" }]} /><output data-testid="snapshot">{JSON.stringify(list.values)}</output><button onClick={() => list.restore({ columns: "count", density: "compact", page: "2" })}>Restore view</button></>;
}
describe("list presentation", () => {
  it("chooses columns and density and restores them from SavedView state", async () => {
    const { container } = render(<MemoryRouter><Table /></MemoryRouter>);
    fireEvent.click(screen.getByText("Columns"));
    fireEvent.click(screen.getByRole("checkbox", { name: "Count" }));
    expect(screen.queryByRole("columnheader", { name: "Count" })).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Name" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Density"), { target: { value: "compact" } });
    expect(screen.getByTestId("snapshot")).toHaveTextContent('"density":"compact"');
    expect(screen.getByRole("cell", { name: "Drill" })).toHaveClass("py-1");
    fireEvent.click(screen.getByText("Restore view"));
    expect(screen.queryByRole("columnheader", { name: "Name" })).not.toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Count" })).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });
  it("falls back to available columns when a saved column has been retired", () => {
    render(<MemoryRouter initialEntries={["/?columns=retired&density=comfortable"]}><Table /></MemoryRouter>);
    expect(screen.getByRole("columnheader", { name: "Name" })).toBeInTheDocument();
  });
  it("keeps the existing comfortable spacing for tables without presentation controls", () => {
    render(<DataTable data={[{ name: "Drill" }]} columns={[{ key: "name", header: "Name" }]} />);
    expect(screen.getByRole("cell", { name: "Drill" })).toHaveClass("py-2");
  });
});
