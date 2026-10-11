import type { TenantBootstrap } from "./api";

export type PublicHome = "inventory" | "events" | "bookings" | "machines" | "membership" | "none";

export function publicHome(bootstrap: TenantBootstrap): PublicHome {
  if (bootstrap.makerspace.public_site_enabled === false) return "none";
  const modules = new Set(bootstrap.modules);
  const available: Record<Exclude<PublicHome, "none">, boolean> = {
    inventory: modules.has("public_inventory") && bootstrap.features.includes("loans.enabled")
      && bootstrap.makerspace.public_inventory_enabled !== false,
    events: modules.has("events"),
    bookings: modules.has("bookings"),
    machines: modules.has("machines"),
    membership: modules.has("membership"),
  };
  const selected = bootstrap.makerspace.public_landing_page;
  if (selected && selected !== "auto" && available[selected]) return selected;
  return (["inventory", "events", "bookings", "machines", "membership"] as const)
    .find((family) => available[family]) ?? "none";
}
