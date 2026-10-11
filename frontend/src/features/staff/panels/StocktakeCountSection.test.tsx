import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { CountSection } from "./StocktakeCountSection";
import type { Makerspace } from "./shared";

const state = vi.hoisted(() => ({ blind: true }));
vi.mock("./shared", () => ({ useStaffGet: (_key: unknown, path: string) => ({
  data: !path ? undefined : path.includes("/assets") ? { results: [{ id: 2, asset_tag: "DRILL-2", status: "lost" }] } :
    path.includes("/inventory?") ? { results: [{ id: 1, name: "Drill", tracking_mode: "individual" }] } :
    path.includes("/containers?") ? { results: [] } : { id: 7, status: "counting", blind: state.blind, lines: [] },
  isLoading: false,
}) }));
vi.mock("../../../components/ui/QrScanner", () => ({ default: () => null }));

beforeEach(() => { state.blind = true; });

it("hides stored asset condition in a blind count selector", () => {
  render(<QueryClientProvider client={new QueryClient()}>
    <CountSection makerspace={{ id: 1 } as Makerspace} stocktakeId={7} />
  </QueryClientProvider>);
  fireEvent.change(screen.getByLabelText("Count type"), { target: { value: "asset" } });
  fireEvent.change(screen.getByLabelText("Product for asset"), { target: { value: "1" } });
  expect(screen.getByRole("option", { name: "DRILL-2" })).toBeInTheDocument();
  expect(screen.queryByRole("option", { name: "DRILL-2 (lost)" })).not.toBeInTheDocument();
});

it("shows stored asset condition for a normal count", () => {
  state.blind = false;
  render(<QueryClientProvider client={new QueryClient()}>
    <CountSection makerspace={{ id: 1 } as Makerspace} stocktakeId={7} />
  </QueryClientProvider>);
  fireEvent.change(screen.getByLabelText("Count type"), { target: { value: "asset" } });
  fireEvent.change(screen.getByLabelText("Product for asset"), { target: { value: "1" } });
  expect(screen.getByRole("option", { name: "DRILL-2 (lost)" })).toBeInTheDocument();
});
