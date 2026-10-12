import { useMemo, useState } from "react";

import type { Product, RequestCartItem } from "../../../types/inventory";

function maxQuantity(product: Product): number {
  if (
    product.availability?.mode === "exact_count" &&
    typeof product.availability.count === "number"
  ) {
    return product.availability.count;
  }

  return 99;
}

/** Cart state for the public inventory page: a product-id keyed map plus its two mutators. */
export function useInventoryCart() {
  const [cart, setCart] = useState<Record<number, RequestCartItem>>({});
  const selectedItems = useMemo(() => Object.values(cart), [cart]);

  function incrementItem(product: Product) {
    if (product.availability?.label === "Unavailable") {
      return;
    }

    setCart((current) => {
      const existing = current[product.id];
      const quantity = Math.min((existing?.quantity ?? 0) + 1, maxQuantity(product));
      return {
        ...current,
        [product.id]: {
          productId: product.id,
          name: product.name,
          quantity,
        },
      };
    });
  }

  function decrementItem(product: Product) {
    setCart((current) => {
      const existing = current[product.id];
      if (!existing || existing.quantity <= 1) {
        const next = { ...current };
        delete next[product.id];
        return next;
      }

      return {
        ...current,
        [product.id]: {
          ...existing,
          quantity: existing.quantity - 1,
        },
      };
    });
  }

  function clearCart() {
    setCart({});
  }

  return { cart, selectedItems, incrementItem, decrementItem, clearCart };
}
