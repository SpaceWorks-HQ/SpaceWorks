export type ResolveTarget =
  | { type: "product"; id: number; name: string }
  | { type: "asset"; id: number; asset_tag: string; product: string; status: string }
  | { type: "box"; id: number; label: string; code: string };
export type ResolvedQr = { id: number; makerspace: number; makerspace_id?: number; payload: string; status: string };
export type Resolved = { qr: ResolvedQr; target: ResolveTarget; allowed_actions: string[] };
export type Rebound = { qr: ResolvedQr; target: ResolveTarget };
export type BoxContents = {
  products: { id: number; name: string; available_quantity: number }[];
  assets: { id: number; asset_tag: string; product: string; status: string }[];
};
export type ListResponse<T> = T[] | { results: T[] };

export function rows<T>(data?: ListResponse<T>) {
  if (!data) return [];
  return Array.isArray(data) ? data : data.results;
}
