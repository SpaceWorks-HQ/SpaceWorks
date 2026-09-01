import { Modal } from "../../components/ui/Modal";
import type { Product } from "../../types/inventory";
import { AvailabilityBadge } from "./AvailabilityBadge";

type ProductQuickViewModalProps = {
  product: Product | null;
  open: boolean;
  onClose: () => void;
};

function trackingLabel(product: Product): string {
  if (product.tracking_mode === "individual") return "Serialized";
  if (product.tracking_mode === "quantity") return "Quantity-tracked";
  return "Catalog item";
}

export function ProductQuickViewModal({
  product,
  open,
  onClose,
}: ProductQuickViewModalProps) {
  if (!product) return null;

  const description = product.description.trim() || "No description provided.";

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Item quick view"
      size="xl"
      backdrop="blur"
      footer={(
        <div className="flex flex-wrap items-center justify-end gap-2">
          <button className="desk-button-primary" type="button" onClick={onClose}>
            Close
          </button>
        </div>
      )}
    >
      <div className="grid min-w-0 gap-5 md:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="min-w-0 overflow-hidden rounded-xl border border-line bg-surface">
          <div className="relative aspect-[4/3] w-full overflow-hidden bg-surface md:aspect-square">
            {product.image_url ? (
              <img
                src={product.image_url}
                alt={product.name}
                className="h-full w-full object-cover"
              />
            ) : (
              <div className="blueprint-bg grid h-full w-full place-items-center">
                <span className="font-display text-6xl font-bold uppercase text-ink/15">
                  {product.name.slice(0, 2)}
                </span>
              </div>
            )}
          </div>
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line pb-4">
            <div className="min-w-0">
              <p className="eyebrow text-secondary-ink">
                ID: {String(product.id).padStart(4, "0")}
              </p>
              <h2 className="title-page mt-2 break-words leading-tight">
                {product.name}
              </h2>
            </div>
            <AvailabilityBadge availability={product.availability} />
          </div>

          <div className="flex flex-wrap gap-2">
            <span className="chip chip-active border-secondary bg-secondary text-on-secondary">
              {trackingLabel(product)}
            </span>
            {product.category_name ? (
              <span className="chip">{product.category_name}</span>
            ) : null}
          </div>

          <div className="rounded-xl border border-line bg-bg p-4">
            <h3 className="title-section">
              Description
            </h3>
            <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-6 text-ink">
              {description}
            </p>
          </div>
        </div>
      </div>
    </Modal>
  );
}
