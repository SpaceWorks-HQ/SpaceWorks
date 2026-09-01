import type { Availability, Product } from "../../types/inventory";

type ProductCardProps = {
  product: Product;
  quantity: number;
  onDecrement: () => void;
  onIncrement: () => void;
  onOpenDetails: () => void;
};

function isUnavailable(product: Product): boolean {
  return product.availability?.label === "Unavailable";
}

function statusChip(availability: Availability): { text: string; cls: string } | null {
  if (availability === null) {
    return null;
  }
  const label = availability.label ?? "Available";
  const count =
    availability.mode === "exact_count" && availability.count != null
      ? availability.count
      : null;

  if (label === "Unavailable") {
    return { text: "Unavailable", cls: "chip" };
  }
  if (label === "Limited") {
    return {
      text: count != null ? `Limited (${count})` : "Limited",
      cls: "chip border-warn bg-warn text-on-warn dark:bg-warn/15 dark:text-warn-ink",
    };
  }
  return {
    text: count != null ? `Available (${count})` : "Available",
    cls: "chip chip-available",
  };
}

export function ProductCard({
  product,
  quantity,
  onDecrement,
  onIncrement,
  onOpenDetails,
}: ProductCardProps) {
  const disabled = isUnavailable(product);
  const chip = statusChip(product.availability);
  const idLabel = `ID: ${String(product.id).padStart(4, "0")}`;

  return (
    <article className="group flex h-full flex-col rounded-xl border border-line bg-panel shadow-soft transition-transform duration-150 hover:-translate-y-0.5 hover:shadow-soft-lg">
      <button
        className="relative h-44 overflow-hidden rounded-t-xl border-b border-line bg-surface text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
        type="button"
        onClick={onOpenDetails}
        aria-label={`Open details for ${product.name}`}
      >
        {product.image_url ? (
          <img
            src={product.image_url}
            alt={product.name}
            loading="lazy"
            className="h-full w-full object-cover transition-transform duration-200 group-hover:scale-[1.02]"
          />
        ) : (
          <div className="blueprint-bg grid h-full w-full place-items-center">
            <span className="font-display text-4xl font-bold uppercase text-ink/15">
              {product.name.slice(0, 2)}
            </span>
          </div>
        )}
        {chip ? (
          <span className={`absolute right-2 top-2 max-w-[calc(100%-1rem)] ${chip.cls}`}>{chip.text}</span>
        ) : null}
      </button>

      <div className="flex flex-1 flex-col p-4">
        <h2 className="title-panel">
          <button
            className="min-h-11 break-words text-left underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
            type="button"
            onClick={onOpenDetails}
          >
            {product.name}
          </button>
        </h2>
        <p className="eyebrow mt-1">{idLabel}</p>
        <p className="mt-2 line-clamp-2 text-sm leading-6 text-muted">
          {product.description || "No description provided."}
        </p>
        {product.category_name ? (
          <div className="mt-3 flex flex-wrap gap-2">
            <span className="chip">{product.category_name}</span>
          </div>
        ) : null}

        <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-4">
          <div className="flex items-center rounded-lg border border-line bg-bg">
            <button
              aria-label={`Remove ${product.name}`}
              className="h-11 w-11 font-mono text-lg font-semibold text-ink transition hover:bg-surface hover:text-ink disabled:cursor-not-allowed disabled:text-muted"
              disabled={quantity === 0}
              type="button"
              onClick={onDecrement}
            >
              -
            </button>
            <span className="grid h-11 min-w-11 place-items-center border-x border-line px-2 font-mono text-sm font-semibold text-ink">
              {quantity}
            </span>
            <button
              aria-label={`Add ${product.name}`}
              className="h-11 w-11 font-mono text-lg font-semibold text-ink transition hover:bg-surface hover:text-ink disabled:cursor-not-allowed disabled:text-muted"
              disabled={disabled}
              type="button"
              onClick={onIncrement}
            >
              +
            </button>
          </div>
          <button
            className="inline-flex min-h-11 min-w-0 items-center break-words font-mono text-xs font-semibold tracking-tight text-secondary-ink underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
            type="button"
            onClick={onOpenDetails}
          >
            Details
          </button>
        </div>
      </div>
    </article>
  );
}
