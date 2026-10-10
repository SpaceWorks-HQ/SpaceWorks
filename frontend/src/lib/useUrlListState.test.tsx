import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider, useLocation, useNavigate } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { readListState, useUrlListState } from "./useUrlListState";

function Harness() {
  const list = useUrlListState({ q: "", ordering: "name", page: "1", status: "" });
  const location = useLocation();
  const navigate = useNavigate();
  return <>
    <output data-testid="state">{JSON.stringify(list.values)}</output><output data-testid="url">{location.search}</output>
    <input aria-label="Search" value={list.values.q} onChange={(e) => list.setFilter("q", e.target.value)} />
    <button onClick={() => list.setPage(3)}>Page three</button><button onClick={() => list.setFilter("ordering", "-name")}>Descending</button>
    <button onClick={() => list.restore({ q: "a & b", ordering: "-name", page: "2" })}>Restore saved</button>
    <button onClick={() => navigate(-1)}>Back</button><button onClick={() => navigate(1)}>Forward</button>
  </>;
}

describe("useUrlListState", () => {
  it("round trips encoded filters, sort and page through browser navigation", async () => {
    const router = createMemoryRouter([{ path: "/", element: <Harness /> }], { initialEntries: ["/?q=drill&page=2&keep=yes"] });
    render(<RouterProvider router={router} />);
    expect(screen.getByLabelText("Search")).toHaveValue("drill");
    fireEvent.click(screen.getByText("Page three"));
    expect(screen.getByTestId("state")).toHaveTextContent('"page":"3"');
    fireEvent.click(screen.getByText("Descending"));
    expect(screen.getByTestId("state")).toHaveTextContent('"page":"1"');
    expect(screen.getByTestId("url")).toHaveTextContent("keep=yes");
    fireEvent.click(screen.getByText("Back"));
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent('"page":"3"'));
    fireEvent.click(screen.getByText("Forward"));
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent('"ordering":"-name"'));
    fireEvent.click(screen.getByText("Restore saved"));
    expect(screen.getByLabelText("Search")).toHaveValue("a & b");
    expect(screen.getByTestId("state")).toHaveTextContent('"page":"2"');
    expect(screen.getByTestId("url")).toHaveTextContent("q=a+%26+b");
  });

  it("rejects invalid and unbounded page numbers", () => {
    for (const page of ["0", "-1", "NaN", "1.5", "10000000"]) expect(readListState(new URLSearchParams({ page }), { page: "1" }).page).toBe("1");
  });

  it("resets every queue page when a filter changes", () => {
    function Queues() {
      const state = useUrlListState({ search: "", pendingPage: "1", acceptedPage: "1" });
      return <button onClick={() => state.setFilter("search", "laser")}>{JSON.stringify(state.values)}</button>;
    }
    const router = createMemoryRouter([{ path: "/", element: <Queues /> }], { initialEntries: ["/?pendingPage=4&acceptedPage=3"] });
    render(<RouterProvider router={router} />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("button")).toHaveTextContent('"pendingPage":"1","acceptedPage":"1"');
  });

  it("keeps drawer pagination independent from its parent list", () => {
    function Drawer() {
      const parent = useUrlListState({ q: "", page: "1" });
      const drawer = useUrlListState({ status: "", page: "1" }, "booking-12.");
      return <><output>{JSON.stringify(parent.values)}</output><button onClick={() => drawer.setFilter("status", "approved")}>{JSON.stringify(drawer.values)}</button></>;
    }
    const router = createMemoryRouter([{ path: "/", element: <Drawer /> }], { initialEntries: ["/?q=room&page=3&booking-12.page=4"] });
    render(<RouterProvider router={router} />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("button")).toHaveTextContent('"status":"approved","page":"1"');
    expect(screen.getByRole("status")).toHaveTextContent('"q":"room","page":"3"');
  });
});
