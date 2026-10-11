import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import type { Product } from "../../types/inventory";
import { ProductCard } from "./ProductCard";

it("links the catalogue title to its public item URL while retaining quick view", () => {
  const open = vi.fn();
  const product = { id: 7, name: "Public drill", description: "Woodwork", availability: null, image_url: null } as Product;
  render(<MemoryRouter><ProductCard product={product} quantity={0} onIncrement={vi.fn()} onDecrement={vi.fn()}
    onOpenDetails={open} detailUrl="/m/lab/items/7" /></MemoryRouter>);
  expect(screen.getByRole("link", { name: "Public drill" })).toHaveAttribute("href", "/m/lab/items/7");
  fireEvent.click(screen.getByRole("button", { name: "Quick view" }));
  expect(open).toHaveBeenCalledTimes(1);
  expect(screen.queryByText(/Available|Unavailable|Limited/)).toBeNull();
});
