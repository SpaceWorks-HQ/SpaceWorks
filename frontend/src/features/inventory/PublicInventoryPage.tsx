import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { MakerspaceBrand } from "../../components/MakerspaceBrand";
import { MakerspaceMapLink } from "../../components/MakerspaceMapLink";
import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { ThemeToggle } from "../../components/ThemeToggle";
import { Card } from "../../components/ui/Card";
import { useTenant, useTenantPath } from "../../lib/tenant";
import type {
  Product,
  RequestCartItem,
} from "../../types/inventory";
import { ProductCard } from "./ProductCard";
import { ProductQuickViewModal } from "./ProductQuickViewModal";
import {
  CatalogSidebar,
  EmptyState,
  ErrorState,
  LoadingState,
  formatSlug,
  type View,
} from "./PublicInventoryParts";
import { PublicRequestPanel } from "./PublicRequestPanel";
import { SkipLink } from "../../components/SkipLink";
import {
  usePublicCategories,
  usePublicInventory,
  useTenantBootstrap,
} from "./usePublicInventory";

const PAGE_SIZE = 24;

export function PublicInventoryPage() {
  const { slug } = useParams();
  const tenant = useTenant();
  const makerspaceSlug = tenant.mode === "single" ? tenant.slug : slug ?? "";
  const tenantPath = useTenantPath(makerspaceSlug);
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [query, setQuery] = useState("");
  const [view, setView] = useState<View>({ kind: "all" });
  const [cart, setCart] = useState<Record<number, RequestCartItem>>({});
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const categoryParam = view.kind === "category" ? view.slug : "";
  const sortParam = view.kind === "sort" ? view.sort : "name";
  const bootstrapQuery = useTenantBootstrap(makerspaceSlug, tenant.mode === "central");
  const categoriesQuery = usePublicCategories(makerspaceSlug);
  const inventoryQuery = usePublicInventory(
    makerspaceSlug,
    page,
    query,
    categoryParam,
    sortParam,
  );
  const bootstrap = tenant.mode === "single" ? tenant.bootstrap : bootstrapQuery.data;
  const displayName =
    bootstrap?.branding.display_name ||
    bootstrap?.makerspace.name ||
    formatSlug(makerspaceSlug) ||
    "Makerspace";
  const modules = tenant.mode === "single" ? tenant.modules : new Set(bootstrap?.modules ?? []);
  const requestEnabled = modules.has("request_workflow");
  const categories = categoriesQuery.data ?? [];
  const products = inventoryQuery.data?.results ?? [];
  const pageCount = Math.max(
    1,
    Math.ceil((inventoryQuery.data?.count ?? 0) / PAGE_SIZE),
  );
  const selectedItems = useMemo(() => Object.values(cart), [cart]);

  function maxQuantity(product: Product): number {
    if (
      product.availability?.mode === "exact_count" &&
      typeof product.availability.count === "number"
    ) {
      return product.availability.count;
    }

    return 99;
  }

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

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setQuery(searchInput.trim());
    setPage(1);
  }

  function selectView(next: View) {
    setView(next);
    setPage(1);
  }

  return (
    <main className="desk-shell">
      <SkipLink />
      <header className="border-b border-line bg-panel">
        <div className="mx-auto flex max-w-screen-2xl flex-col gap-2 px-5 py-4 sm:px-8">
          <p className="eyebrow text-secondary-ink">
            Public Inventory
          </p>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="min-w-0">
              <h1 className="title-page">
                <MakerspaceBrand
                  name={displayName}
                  logoUrl={bootstrap?.makerspace.logo_url}
                  size="xl"
                />
              </h1>
              <p className="mt-1 text-sm text-muted">
                Shared tools and equipment published by this makerspace.
              </p>
              <MakerspaceMapLink
                makerspace={bootstrap?.makerspace}
                className="mt-1"
              />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <SpaceWorksBadge />
              <div className="rounded-lg border border-secondary bg-secondary/15 px-3 py-2 font-mono text-sm text-secondary-ink">
                {inventoryQuery.data?.count ?? "-"} listed items
              </div>
              {bootstrap?.makerspace.public_stats_enabled ? (
                <Link className="desk-button" to={tenantPath("stats")}>
                  Stats
                </Link>
              ) : null}
              {modules.has("printing") ? (
                <Link className="desk-button" to={tenantPath("print")}>
                  Request a 3D print
                </Link>
              ) : null}
              {modules.has("events") ? (
                <Link className="desk-button" to={tenantPath("events")}>
                  Events
                </Link>
              ) : null}
              {modules.has("machines") ? (
                <Link className="desk-button" to={tenantPath("machines")}>
                  Machines
                </Link>
              ) : null}
              {modules.has("bookings") ? (
                <Link className="desk-button" to={tenantPath("bookings")}>
                  Book a space
                </Link>
              ) : null}
              <ThemeToggle />
              <Link className="desk-button" to="/admin">
                Staff login
              </Link>
            </div>
          </div>
        </div>
      </header>

      <section className="mx-auto grid max-w-screen-2xl grid-cols-1 gap-5 px-5 py-6 sm:px-8 lg:grid-cols-[200px_minmax(0,1fr)_360px]" id="main-content" tabIndex={-1}>
        <CatalogSidebar
          categories={categories}
          view={view}
          onSelect={selectView}
        />

        <div className="min-w-0 space-y-4">
          <Card>
            <form
              className="flex flex-col gap-3 sm:flex-row"
              onSubmit={submitSearch}
            >
              <input
                className="desk-input min-w-0 flex-1"
                placeholder="Search tools, machines, kits, or materials"
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
              />
              <button className="desk-button-primary" type="submit">
                Search
              </button>
              {query ? (
                <button
                  className="desk-button"
                  type="button"
                  onClick={() => {
                    setSearchInput("");
                    setQuery("");
                    setPage(1);
                  }}
                >
                  Clear
                </button>
              ) : null}
            </form>
          </Card>

          {inventoryQuery.isLoading ? <LoadingState /> : null}

          {inventoryQuery.isError ? (
            <ErrorState error={inventoryQuery.error} />
          ) : null}

          {inventoryQuery.data && products.length === 0 ? (
            <EmptyState query={query} />
          ) : null}

          {products.length > 0 ? (
            <>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                {products.map((product) => (
                  <ProductCard
                    key={product.id}
                    product={product}
                    quantity={cart[product.id]?.quantity ?? 0}
                    onDecrement={() => decrementItem(product)}
                    onIncrement={() => incrementItem(product)}
                    onOpenDetails={() => setSelectedProduct(product)}
                  />
                ))}
              </div>
              <div className="desk-panel flex flex-wrap items-center justify-between gap-3 p-3">
                <p className="min-w-0 font-mono text-sm text-muted">
                  Page {page} of {pageCount}
                  {inventoryQuery.isFetching ? " loading..." : ""}
                </p>
                <div className="flex flex-wrap gap-2">
                  <button
                    className="desk-button"
                    disabled={!inventoryQuery.data?.previous || page === 1}
                    type="button"
                    onClick={() => setPage((current) => Math.max(1, current - 1))}
                  >
                    Previous
                  </button>
                  <button
                    className="desk-button"
                    disabled={!inventoryQuery.data?.next}
                    type="button"
                    onClick={() =>
                      setPage((current) => Math.min(pageCount, current + 1))
                    }
                  >
                    Next
                  </button>
                </div>
              </div>
            </>
          ) : null}
        </div>

        <div className="min-w-0">
          <PublicRequestPanel
            items={selectedItems}
            makerspaceSlug={makerspaceSlug}
            onClear={() => setCart({})}
            disabled={!requestEnabled}
          />
        </div>
      </section>

      <ProductQuickViewModal
        product={selectedProduct}
        open={Boolean(selectedProduct)}
        onClose={() => setSelectedProduct(null)}
      />
    </main>
  );
}
