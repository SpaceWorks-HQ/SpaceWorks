import { Field } from "../../../components/ui";
import type { Product } from "./shared";

type PrinterOption = { id: number; name: string };

export type ContainerOption = { id: number; label: string };
export type HardwareMode = "create" | "topup";
export type PrintingTarget = "spool" | "printer";

export type HardwareForm = {
  mode: HardwareMode;
  quantity: string;
  productId: string;
  name: string;
  description: string;
  category: string;
  box: string;
  trackingMode: "quantity" | "individual";
  isPublic: boolean;
  publicAvailabilityMode: "exact_count" | "status_only" | "hidden";
  showPublicCount: boolean;
  publicSelfCheckoutEnabled: boolean;
};

export type PrintingForm = {
  target: PrintingTarget;
  printerId: string;
  material: string;
  color: string;
  brand: string;
  initialWeight: string;
  remainingWeight: string;
  printerName: string;
  printerModel: string;
  printerStatus: "active" | "maintenance" | "offline";
};

export function HardwareMoveForm({ form, setForm, products, categories, containers }: {
  form: HardwareForm;
  setForm: (form: HardwareForm) => void;
  products: Product[];
  categories: { id: number; name: string }[];
  containers: ContainerOption[];
}) {
  return (
    <div className="grid gap-3">
      <Segmented values={["create", "topup"]} value={form.mode} label={(mode) => mode === "create" ? "Create item" : "Top up"} onChange={(mode) => setForm({ ...form, mode })} />
      <Field label="Quantity"><input className="desk-input" type="number" min="1" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} /></Field>
      {form.mode === "topup" ? (
        <Field label="Existing product">
          <select className="desk-input" value={form.productId} onChange={(e) => setForm({ ...form, productId: e.target.value })}>
            <option value="">Select product</option>
            {products.map((product) => <option key={product.id} value={product.id}>{product.name} ({product.available_quantity} available)</option>)}
          </select>
        </Field>
      ) : (
        <>
          <div className="grid gap-2 sm:grid-cols-2">
            <Field label="Name"><input className="desk-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label="Tracking mode"><select className="desk-input" value={form.trackingMode} onChange={(e) => setForm({ ...form, trackingMode: e.target.value as HardwareForm["trackingMode"] })}><option value="quantity">Quantity</option><option value="individual">Individual</option></select></Field>
          </div>
          <Field label="Description"><textarea className="desk-input h-20" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
          <div className="grid gap-2 sm:grid-cols-2">
            <Field label="Category"><select className="desk-input" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}><option value="">Uncategorized</option>{categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></Field>
            <Field label="Container"><select className="desk-input" value={form.box} onChange={(e) => setForm({ ...form, box: e.target.value })}><option value="">No container</option>{containers.map((container) => <option key={container.id} value={container.id}>{container.label}</option>)}</select></Field>
          </div>
          <div className="grid gap-2 sm:grid-cols-4">
            <Check label="Public" checked={form.isPublic} onChange={(value) => setForm({ ...form, isPublic: value })} />
            <Check label="Show count" checked={form.showPublicCount} onChange={(value) => setForm({ ...form, showPublicCount: value })} />
            <Check label="Self checkout" checked={form.publicSelfCheckoutEnabled} onChange={(value) => setForm({ ...form, publicSelfCheckoutEnabled: value })} />
            <Field label="Visibility"><select className="desk-input" value={form.publicAvailabilityMode} onChange={(e) => setForm({ ...form, publicAvailabilityMode: e.target.value as HardwareForm["publicAvailabilityMode"] })}><option value="status_only">Status only</option><option value="exact_count">Exact count</option><option value="hidden">Hidden</option></select></Field>
          </div>
        </>
      )}
    </div>
  );
}

export function PrintingMoveForm({ form, setForm, printers }: { form: PrintingForm; setForm: (form: PrintingForm) => void; printers: PrinterOption[] }) {
  return (
    <div className="grid gap-3">
      <Segmented values={["spool", "printer"]} value={form.target} label={(target) => target === "spool" ? "Spool" : "Printer"} onChange={(target) => setForm({ ...form, target })} />
      {form.target === "spool" ? (
        <>
          <Field label="Printer"><select className="desk-input" value={form.printerId} onChange={(e) => setForm({ ...form, printerId: e.target.value })}><option value="">Unassigned printer</option>{printers.map((printer) => <option key={printer.id} value={printer.id}>{printer.name}</option>)}</select></Field>
          <div className="grid gap-2 sm:grid-cols-2"><Field label="Material"><input className="desk-input" value={form.material} onChange={(e) => setForm({ ...form, material: e.target.value })} /></Field><Field label="Brand"><input className="desk-input" value={form.brand} onChange={(e) => setForm({ ...form, brand: e.target.value })} /></Field></div>
          <Field label="Color"><input className="desk-input" value={form.color} onChange={(event) => setForm({ ...form, color: event.target.value })} /></Field>
          <div className="grid gap-2 sm:grid-cols-2">
            <Field label="Initial weight (g)"><input className="desk-input" type="number" min="0" step="0.01" value={form.initialWeight} onChange={(e) => setForm({ ...form, initialWeight: e.target.value, remainingWeight: form.remainingWeight || e.target.value })} /></Field>
            <Field label="Remaining weight (g)"><input className="desk-input" type="number" min="0" step="0.01" value={form.remainingWeight} onChange={(e) => setForm({ ...form, remainingWeight: e.target.value })} /></Field>
          </div>
        </>
      ) : (
        <>
          <Field label="Printer name"><input className="desk-input" value={form.printerName} onChange={(e) => setForm({ ...form, printerName: e.target.value })} /></Field>
          <div className="grid gap-2 sm:grid-cols-2"><Field label="Model"><input className="desk-input" value={form.printerModel} onChange={(e) => setForm({ ...form, printerModel: e.target.value })} /></Field><Field label="Status"><select className="desk-input" value={form.printerStatus} onChange={(e) => setForm({ ...form, printerStatus: e.target.value as PrintingForm["printerStatus"] })}><option value="active">Active</option><option value="maintenance">Maintenance</option><option value="offline">Offline</option></select></Field></div>
        </>
      )}
    </div>
  );
}

function Segmented<T extends string>({ values, value, label, onChange }: { values: T[]; value: T; label: (value: T) => string; onChange: (value: T) => void }) {
  return <div className="inline-flex w-max rounded-md border border-line bg-surface p-1">{values.map((item) => <button key={item} type="button" className={value === item ? "desk-button-primary" : "desk-button-ghost"} onClick={() => onChange(item)}>{label(item)}</button>)}</div>;
}

function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return <label className="inline-flex items-center gap-2 text-sm"><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /> {label}</label>;
}
