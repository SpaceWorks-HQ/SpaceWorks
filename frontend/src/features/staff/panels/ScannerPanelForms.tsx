import type { Makerspace, Product } from "./shared";

export function ScannerRebindForm({
  makerspaceLabel,
  productRows,
  productsLoading,
  selectedProductId,
  onSelectProduct,
  newName,
  onNewNameChange,
  pending,
  onSubmit,
  onCancel,
  productError,
  rebindError,
}: {
  makerspaceLabel: string;
  productRows: Product[];
  productsLoading: boolean;
  selectedProductId: string;
  onSelectProduct: (value: string) => void;
  newName: string;
  onNewNameChange: (value: string) => void;
  pending: boolean;
  onSubmit: () => void;
  onCancel: () => void;
  productError?: string;
  rebindError?: string;
}) {
  return (
    <form
      className="mt-3 grid gap-2 rounded-md border border-line bg-bg p-3 text-sm"
      onSubmit={(event) => {
        event.preventDefault();
        if (selectedProductId) onSubmit();
      }}
    >
      <label className="grid gap-1">
        <span className="eyebrow">QR makerspace</span>
        <input
          className="desk-input"
          value={makerspaceLabel}
          disabled
        />
      </label>
      <label className="grid gap-1">
        <span className="eyebrow">Target product</span>
        <select
          className="desk-input"
          value={selectedProductId}
          disabled={productsLoading || !productRows.length}
          onChange={(event) => onSelectProduct(event.target.value)}
        >
          {productRows.map((product) => (
            <option key={product.id} value={product.id}>{product.name}</option>
          ))}
        </select>
      </label>
      <input
        className="desk-input"
        aria-label="Rename target"
        placeholder="Rename (optional)"
        value={newName}
        onChange={(event) => onNewNameChange(event.target.value)}
      />
      <div className="flex flex-wrap gap-2">
        <button className="desk-button-primary" type="submit" disabled={!selectedProductId || pending}>
          {pending ? "Saving..." : "Save"}
        </button>
        <button className="desk-button-ghost" type="button" onClick={onCancel}>Cancel</button>
      </div>
      {productError ? <p className="text-sm text-danger">{productError}</p> : null}
      {rebindError ? <p className="text-sm text-danger">{rebindError}</p> : null}
    </form>
  );
}

export function ScannerMoveAssetForm({
  destinationMakerspaces,
  destMakerspaceId,
  onDestMakerspaceChange,
  destProductId,
  onDestProductChange,
  destinationProductRows,
  destinationProductsLoading,
  moveTag,
  onMoveTagChange,
  pending,
  onSubmit,
  onCancel,
  destinationProductError,
  moveError,
}: {
  destinationMakerspaces: Makerspace[];
  destMakerspaceId: string;
  onDestMakerspaceChange: (value: string) => void;
  destProductId: string;
  onDestProductChange: (value: string) => void;
  destinationProductRows: Product[];
  destinationProductsLoading: boolean;
  moveTag: string;
  onMoveTagChange: (value: string) => void;
  pending: boolean;
  onSubmit: () => void;
  onCancel: () => void;
  destinationProductError?: string;
  moveError?: string;
}) {
  return (
    <form
      className="mt-3 grid gap-2 rounded-md border border-line bg-bg p-3 text-sm"
      onSubmit={(event) => {
        event.preventDefault();
        if (destMakerspaceId) onSubmit();
      }}
    >
      <label className="grid gap-1">
        <span className="eyebrow">Destination makerspace</span>
        <select
          className="desk-input"
          required
          value={destMakerspaceId}
          onChange={(event) => {
            onDestMakerspaceChange(event.target.value);
          }}
        >
          <option value="">Select makerspace</option>
          {destinationMakerspaces.map((space) => (
            <option key={space.id} value={space.id}>{space.name}</option>
          ))}
        </select>
      </label>
      <label className="grid gap-1">
        <span className="eyebrow">Destination product</span>
        <select
          className="desk-input"
          value={destProductId}
          disabled={!destMakerspaceId || destinationProductsLoading}
          onChange={(event) => onDestProductChange(event.target.value)}
        >
          <option value="">Auto - match by name or create</option>
          {destinationProductRows.map((product) => (
            <option key={product.id} value={product.id}>{product.name}</option>
          ))}
        </select>
      </label>
      <input
        className="desk-input"
        aria-label="New asset tag"
        placeholder="New asset tag (optional)"
        value={moveTag}
        onChange={(event) => onMoveTagChange(event.target.value)}
      />
      <div className="flex flex-wrap gap-2">
        <button className="desk-button-primary" type="submit" disabled={!destMakerspaceId || pending}>
          {pending ? "Moving..." : "Move"}
        </button>
        <button className="desk-button-ghost" type="button" onClick={onCancel}>Cancel</button>
      </div>
      {destinationProductError ? <p className="text-sm text-danger">{destinationProductError}</p> : null}
      {moveError ? <p className="text-sm text-danger">{moveError}</p> : null}
    </form>
  );
}
