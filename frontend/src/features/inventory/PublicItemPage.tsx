import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { PageMetadata } from "../../components/PageMetadata";
import { SiteFooter } from "../../components/SiteFooter";
import { SkipLink } from "../../components/SkipLink";
import { ThemeToggle } from "../../components/ThemeToggle";
import { Card, Skeleton } from "../../components/ui";
import { StructuredApiError, tenantPublicRequest } from "../../lib/api";
import { useTenant, useTenantPath } from "../../lib/tenant";
import { useTenantBranding } from "../../lib/useTenantBranding";
import type { Product } from "../../types/inventory";
import { AvailabilityBadge } from "./AvailabilityBadge";
import { useTenantBootstrap } from "./usePublicInventory";

// The numeric identity is stable even if the optional readable suffix changes.
export function publicItemId(value: string) {
  const id = value.split("-")[0];
  return /^[1-9]\d*(?:-[^/]+)?$/.test(value) && Number.isSafeInteger(Number(id)) ? id : null;
}

export function PublicItemPage() {
  const { slug = "", itemId = "" } = useParams();
  const tenant = useTenant();
  const spaceSlug = tenant.mode === "single" ? tenant.slug : slug;
  const tenantPath = useTenantPath(spaceSlug);
  const bootstrapQuery = useTenantBootstrap(spaceSlug, tenant.mode === "central");
  const bootstrap = tenant.mode === "single" ? tenant.bootstrap : bootstrapQuery.data;
  const brandStyle = useTenantBranding(bootstrap);
  const id = publicItemId(itemId);
  const item = useQuery({
    queryKey: ["public-inventory-detail", spaceSlug, id],
    queryFn: () => tenantPublicRequest<Product>(spaceSlug, `/public/${encodeURIComponent(spaceSlug)}/inventory/${id}/`),
    enabled: Boolean(spaceSlug && id),
    retry: (count, error) => !(error instanceof StructuredApiError && error.status < 500) && count < 2,
  });
  const product = item.error ? undefined : item.data;
  const name = bootstrap?.branding.display_name || bootstrap?.makerspace.name || "Makerspace";
  const missing = !id || (item.error instanceof StructuredApiError && item.error.status === 404);
  const disabled = item.error instanceof StructuredApiError && item.error.status === 400;
  const title = missing ? "Item not found" : disabled ? "Inventory is not enabled" : product?.name ?? "Item details";
  const description = product?.description || `Browse public tools and equipment at ${name}.`;
  const modules = new Set(bootstrap?.modules ?? []);
  return <main style={brandStyle} className="desk-shell flex min-h-screen flex-col">
    <PageMetadata title={`${title} · ${name}`} description={description} path={tenantPath(`items/${product?.id ?? id ?? itemId}`)} image={product?.image_url || bootstrap?.makerspace.logo_url} siteName={name} />
    <SkipLink />
    <header className="border-b border-line bg-panel"><div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-5 py-4">
      <Link className="desk-button" to={tenantPath()}>Back to {name}</Link><ThemeToggle />
    </div></header>
    <section id="main-content" tabIndex={-1} className="mx-auto w-full max-w-5xl flex-1 px-5 py-8">
      {id && item.isLoading ? <><h1 className="title-page">Item details</h1><p role="status" className="my-3 text-sm text-muted">Loading item...</p><Skeleton className="h-64 w-full" /></> : null}
      {missing || item.error ? <Card><h1 className="title-page">{missing || disabled ? title : "Item unavailable"}</h1><p className="mt-3 text-sm text-muted">{missing ? "This item is not available on the public catalogue." : disabled ? "This makerspace is not publishing inventory." : "Could not load this item. Please try again."}</p>{!missing && !disabled ? <button type="button" className="desk-button mt-4" onClick={() => item.refetch()}>Retry</button> : null}</Card> : null}
      {product ? <article className="desk-panel grid gap-6 p-5 md:grid-cols-2">
        {product.image_url ? <img src={product.image_url} alt={product.name} className="w-full rounded-xl object-contain" /> : null}
        <div><h1 className="title-page">{product.name}</h1><div className="mt-3"><AvailabilityBadge availability={product.availability} /></div>
          {product.category_name ? <p className="eyebrow mt-3">{product.category_name}</p> : null}
          <p className="mt-5 whitespace-pre-wrap break-words text-sm leading-6">{product.description || "No description provided."}</p>
          {modules.has("request_workflow") ? <Link className="desk-button-secondary mt-5 inline-flex" to={tenantPath()}>Request from the catalogue</Link> : null}
        </div>
      </article> : null}
    </section><SiteFooter branding={bootstrap?.branding} />
  </main>;
}
