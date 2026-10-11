import type { Product } from "./shared";
import type { KitComponent } from "../../inventory/KitChecklist";

type MasterData = { manufacturer?: string; model?: string; sku?: string; barcode?: string; supplier?: string;
  reorder_point?: number; reorder_quantity?: number; kit_components?: KitComponent[] };

export type AdminProduct = Product & MasterData & {
  borrowing_terms?: string;
  reserved_quantity: number;
  needs_fix_quantity: number;
  storage_location: string;
  show_public_count: boolean;
  public_availability_mode: string;
  is_archived: boolean;
};
export type ItemForm = {
  manufacturer: string; model: string; sku: string; barcode: string; supplier: string;
  reorder_point: string; reorder_quantity: string; kit_components?: KitComponent[];
  name: string; tracking_mode: string; category: string; description: string; borrowing_terms: string; total_quantity: string; available_quantity: string;
  storage_location: string; is_public: boolean; public_self_checkout_enabled: boolean; show_public_count: boolean; public_availability_mode: string;
};
export type AdjustmentForm = { delta_available: string; delta_damaged: string; delta_lost: string; reason: string };
export type InventoryAssetRow = { id: number; asset_tag: string; serial_number: string; status: string; box: number | null; box_label: string | null; qr_code_id: number | null; qr_payload: string | null; notes: string; public_self_checkout_enabled: boolean };
export type Actor = { username: string; role: string };
export type LendingHistoryEntry = { id: number; username: string; issued_at: string; quantity: number; accepted_by: Actor | null; issued_by: Actor | null };
export type LendingHistoryResponse = { product_id: number; last_borrower: LendingHistoryEntry | null; recent: LendingHistoryEntry[] };
export type QrHistoryEntry = { id: string; source: string; context: string; actor: number | null; created_at: string };
export type QrHistoryResponse = { product?: number; asset?: number; scans: QrHistoryEntry[] };

export const emptyForm: ItemForm = {
  manufacturer: "", model: "", sku: "", barcode: "", supplier: "", reorder_point: "0", reorder_quantity: "0",
  name: "", tracking_mode: "quantity", category: "", description: "", borrowing_terms: "", total_quantity: "1", available_quantity: "1",
  storage_location: "", is_public: true, public_self_checkout_enabled: false, show_public_count: false, public_availability_mode: "status_only",
};
export const emptyAdjust: AdjustmentForm = { delta_available: "0", delta_damaged: "0", delta_lost: "0", reason: "" };

export function payloadFromForm(form: ItemForm, includeQuantities: boolean) {
  return {
    name: form.name.trim(), tracking_mode: form.tracking_mode, category: form.category ? Number(form.category) : null, description: form.description,
    borrowing_terms: form.borrowing_terms, storage_location: form.storage_location, is_public: form.is_public, public_self_checkout_enabled: form.public_self_checkout_enabled,
    show_public_count: form.show_public_count, public_availability_mode: form.public_availability_mode,
    manufacturer: form.manufacturer.trim(), model: form.model.trim(), sku: form.sku.trim(), barcode: form.barcode.trim(),
    supplier: form.supplier.trim(), reorder_point: Number(form.reorder_point), reorder_quantity: Number(form.reorder_quantity),
    ...(form.kit_components !== undefined ? { kit_components: form.kit_components } : {}),
    ...(includeQuantities ? { total_quantity: Number(form.total_quantity || 0), available_quantity: Number(form.available_quantity || 0) } : {}),
  };
}

export function adjustPayload(form: AdjustmentForm) {
  return { delta_available: Number(form.delta_available || 0), delta_damaged: Number(form.delta_damaged || 0), delta_lost: Number(form.delta_lost || 0), reason: form.reason.trim() };
}

export function formFromProduct(product: AdminProduct): ItemForm {
  return { name: product.name, tracking_mode: product.tracking_mode, category: product.category ? String(product.category) : "", description: product.description, total_quantity: String(product.total_quantity), available_quantity: String(product.available_quantity), storage_location: product.storage_location ?? "", is_public: product.is_public, public_self_checkout_enabled: product.public_self_checkout_enabled, show_public_count: product.show_public_count, public_availability_mode: product.public_availability_mode,
    borrowing_terms: product.borrowing_terms ?? "", manufacturer: product.manufacturer ?? "", model: product.model ?? "", sku: product.sku ?? "", barcode: product.barcode ?? "",
    supplier: product.supplier ?? "", reorder_point: String(product.reorder_point ?? 0), reorder_quantity: String(product.reorder_quantity ?? 0) };
}

export function defaultToBuyQuantity(product: AdminProduct) {
  const target = Math.ceil(product.total_quantity * 0.2) + 1;
  return String(Math.max(1, target - product.available_quantity));
}

export function formatActor(actor: Actor) {
  return actor.role ? `${actor.username} (${actor.role})` : actor.username;
}

export function humanize(value: string) {
  return value.replace(/_/g, " ").replace(/^\w/, (match) => match.toUpperCase());
}

export function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
