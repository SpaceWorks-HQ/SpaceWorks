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
    <Card className="mx-auto max-w-lg border-secondary text-center">
      <h2 className="title-panel">
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
    <Card className="mx-auto max-w-lg border-secondary text-center">
      <h2 className="title-panel">{error.message}</h2>
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
      ? "desk-nav-item desk-nav-item-active shrink-0 whitespace-nowrap border-secondary bg-secondary text-on-secondary hover:border-secondary hover:bg-secondary hover:text-on-secondary lg:shrink lg:whitespace-normal"
      : "desk-nav-item shrink-0 whitespace-nowrap hover:border-secondary hover:bg-secondary/15 lg:shrink lg:whitespace-normal";
  const countClass = (active: boolean) =>
    active
      ? "ml-2 font-mono text-xs text-on-secondary/80"
      : "ml-2 rounded-full bg-warn px-1.5 font-mono text-xs text-on-warn dark:bg-warn/15 dark:text-warn-ink";

  return (
    <Card
      className="lg:sticky lg:top-0 lg:max-h-[100dvh] lg:overflow-y-auto"
      padding="sm"
    >
      <nav aria-label="Catalog browse">
        <h2 className="title-section px-3">
          Browse
        </h2>
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
            <h3 className="title-section px-3">
              Categories
            </h3>
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
