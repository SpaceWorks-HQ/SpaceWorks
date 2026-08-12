import { Card } from "../../components/ui/Card";
import { Spinner } from "../../components/ui/Spinner";
import type { PublicCategory } from "../../types/inventory";

export type View =
  | { kind: "all" }
  | { kind: "sort"; sort: "popular" | "most_used" }
  | { kind: "category"; slug: string };

export function formatSlug(slug: string): string {
  return slug
    .split("-")
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

export function LoadingState() {
  return (
    <div className="grid min-h-64 place-items-center">
      <Spinner />
    </div>
  );
}

export function EmptyState({ query }: { query: string }) {
  return (
    <Card className="mx-auto max-w-lg text-center">
      <h2 className="text-xl font-semibold text-ink">
        {query ? "No matching items." : "No public items yet."}
      </h2>
      <p className="mt-2 text-sm leading-6 text-muted">
        {query
          ? "Try a different search term or clear the search field."
          : "This makerspace has not shared any inventory items publicly."}
      </p>
    </Card>
  );
}

export function ErrorState({ error }: { error: Error }) {
  return (
    <Card className="mx-auto max-w-lg text-center">
      <h2 className="text-xl font-semibold text-ink">{error.message}</h2>
      <p className="mt-2 text-sm leading-6 text-muted">
        This makerspace may not exist or its public inventory is disabled.
      </p>
    </Card>
  );
}

export function CatalogSidebar({
  categories,
  view,
  onSelect,
}: {
  categories: PublicCategory[];
  view: View;
  onSelect: (view: View) => void;
}) {
  const itemClass = (active: boolean) =>
    active
      ? "desk-nav-item desk-nav-item-active shrink-0 whitespace-nowrap lg:shrink lg:whitespace-normal"
      : "desk-nav-item shrink-0 whitespace-nowrap lg:shrink lg:whitespace-normal";
  const countClass = (active: boolean) =>
    active
      ? "ml-2 text-xs text-on-accent/80"
      : "ml-2 rounded-full bg-warn px-1.5 text-xs text-on-warn dark:bg-[#332b00] dark:text-[#fcdf46]";

  return (
    <Card
      className="lg:sticky lg:top-0 lg:max-h-[100dvh] lg:overflow-y-auto"
      padding="sm"
    >
      <nav aria-label="Catalog browse">
        <p className="px-3 text-xs font-semibold tracking-wide text-muted">
          Browse
        </p>
        <div className="mt-2 flex gap-2 overflow-x-auto lg:block lg:space-y-1 lg:overflow-visible">
          <button
            aria-current={view.kind === "all" ? "page" : undefined}
            className={itemClass(view.kind === "all")}
            type="button"
            onClick={() => onSelect({ kind: "all" })}
          >
            <span>All items</span>
          </button>
          <button
            aria-current={
              view.kind === "sort" && view.sort === "popular"
                ? "page"
                : undefined
            }
            className={itemClass(view.kind === "sort" && view.sort === "popular")}
            type="button"
            onClick={() => onSelect({ kind: "sort", sort: "popular" })}
          >
            <span>Popular</span>
          </button>
          <button
            aria-current={
              view.kind === "sort" && view.sort === "most_used"
                ? "page"
                : undefined
            }
            className={itemClass(
              view.kind === "sort" && view.sort === "most_used",
            )}
            type="button"
            onClick={() => onSelect({ kind: "sort", sort: "most_used" })}
          >
            <span>Most used</span>
          </button>
        </div>

        {categories.length > 0 ? (
          <>
            <div className="my-3 border-t border-line" />
            <p className="px-3 text-xs font-semibold tracking-wide text-muted">
              Categories
            </p>
            <div className="mt-2 flex gap-2 overflow-x-auto lg:block lg:space-y-1 lg:overflow-visible">
              {categories.map((category) => {
                const active =
                  view.kind === "category" && view.slug === category.slug;
                return (
                  <button
                    aria-current={active ? "page" : undefined}
                    className={itemClass(active)}
                    key={category.id}
                    type="button"
                    onClick={() =>
                      onSelect({ kind: "category", slug: category.slug })
                    }
                  >
                    <span className="min-w-0 truncate">{category.name}</span>
                    <span className={countClass(active)}>
                      ({category.product_count})
                    </span>
                  </button>
                );
              })}
            </div>
          </>
        ) : null}
      </nav>
    </Card>
  );
}
