import { Field } from "../../../components/ui";
import type { ItemForm } from "./InventoryPanelShared";

export function ProductMasterFields({ form, setForm }: {
  form: ItemForm; setForm: (update: (current: ItemForm) => ItemForm) => void;
}) {
  const fields = [["manufacturer", "Manufacturer"], ["model", "Model"], ["sku", "SKU"],
    ["barcode", "Barcode"], ["supplier", "Supplier company"]] as const;
  return <fieldset className="grid gap-3 rounded-md border border-line p-3">
    <legend className="text-sm font-medium text-ink">Product master data</legend>
    <div className="grid gap-2 sm:grid-cols-2">{fields.map(([key, label]) => <Field key={key} label={label}>
      <input className="desk-input" value={form[key]} maxLength={key === "sku" || key === "barcode" ? 100 : 200}
        onChange={(event) => setForm((current) => ({ ...current, [key]: event.target.value }))} />
    </Field>)}</div>
    <p className="text-xs text-muted">Use a supplier company name. Keep personal contact details in the existing private procurement records.</p>
    <div className="grid gap-2 sm:grid-cols-2">
      <Field label="Reorder point"><input className="desk-input" type="number" min="0" step="1" value={form.reorder_point}
        onChange={(event) => setForm((current) => ({ ...current, reorder_point: event.target.value }))} /></Field>
      <Field label="Reorder quantity"><input className="desk-input" type="number" min="0" step="1" value={form.reorder_quantity}
        onChange={(event) => setForm((current) => ({ ...current, reorder_quantity: event.target.value }))} /></Field>
    </div>
    <p className="text-xs text-muted">A reorder point of 0 disables alerts and suggestions. Set a reorder quantity to create procurement drafts.</p>
  </fieldset>;
}
