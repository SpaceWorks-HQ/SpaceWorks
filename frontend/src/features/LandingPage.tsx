import { useDeferredValue, useMemo, useState } from "react";
import { Link, Navigate } from "react-router-dom";

import { MakerspaceBrand } from "../components/MakerspaceBrand";
import { MakerspaceMapLink } from "../components/MakerspaceMapLink";
import { SpaceWorksHomeLink, SpaceWorksLogo } from "../components/SpaceWorksLogo";
import { SiteFooter } from "../components/SiteFooter";
import { ThemeToggle } from "../components/ThemeToggle";
import { Card } from "../components/ui/Card";
import { Spinner } from "../components/ui/Spinner";
import type { Makerspace } from "../types/inventory";
import { usePublicMakerspaces } from "./inventory/usePublicInventory";

function normalizeSearch(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, " ");
}

function makerspaceSearchText(makerspace: Makerspace) {
  return normalizeSearch([
    makerspace.name,
    makerspace.public_code,
    makerspace.slug,
    makerspace.location,
  ].filter(Boolean).join(" "));
}

export function LandingPage() {
  const makerspacesQuery = usePublicMakerspaces();
  const [searchInput, setSearchInput] = useState("");
  const searchQuery = normalizeSearch(useDeferredValue(searchInput));
  const searchTokens = useMemo(
    () => searchQuery.split(" ").filter(Boolean),
    [searchQuery],
  );
  const indexedMakerspaces = useMemo(
    () => (makerspacesQuery.data ?? []).map((makerspace) => ({
      makerspace,
      searchText: makerspaceSearchText(makerspace),
    })),
    [makerspacesQuery.data],
  );
  const filteredMakerspaces = useMemo(() => {
    if (!searchTokens.length) return indexedMakerspaces.map(({ makerspace }) => makerspace);
    return indexedMakerspaces
      .filter(({ searchText }) => searchTokens.every((token) => searchText.includes(token)))
      .map(({ makerspace }) => makerspace);
  }, [indexedMakerspaces, searchTokens]);
  const totalMakerspaces = makerspacesQuery.data?.length ?? 0;
  const onlyMakerspace = totalMakerspaces === 1 ? makerspacesQuery.data?.[0] : null;

  if (onlyMakerspace) return <Navigate replace to={`/m/${onlyMakerspace.slug}`} />;

  return (
    <main className="desk-shell flex min-h-screen flex-col">
      <header className="border-b border-line bg-panel">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-5 py-4">
          <SpaceWorksHomeLink className="flex min-w-0 items-center gap-3 text-ink">
            <SpaceWorksLogo className="shrink-0" size={36} />
            <div className="min-w-0">
              <p className="text-sm font-semibold">Space Works</p>
              <p className="text-xs text-muted">Shared equipment portal</p>
            </div>
          </SpaceWorksHomeLink>
          <div className="flex flex-wrap items-center gap-2">
            <ThemeToggle />
            <Link className="desk-button-secondary" to="/admin">Staff login</Link>
          </div>
        </div>
      </header>

      <section className="mx-auto grid max-w-7xl grid-cols-1 gap-6 px-5 py-8 lg:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="desk-panel h-fit p-5">
          <p className="eyebrow text-secondary-ink">Inventory Directory</p>
          <h1 className="title-page mt-3">Makerspaces</h1>
          <p className="mt-3 text-sm leading-6 text-muted">
            Browse public catalogs across connected workshops, labs, and community spaces.
          </p>
          <div className="mt-6 grid grid-cols-2 gap-3 text-sm">
            <div className="rounded-md border border-line bg-surface p-3">
              <p className="font-mono text-2xl font-bold text-ink">
                {makerspacesQuery.isLoading ? "-" : totalMakerspaces}
              </p>
              <p className="eyebrow">Public spaces</p>
            </div>
            <div className="rounded-md border border-line bg-surface p-3">
              <p className="text-2xl font-bold text-success-ink">Live</p>
              <p className="eyebrow">Status access</p>
            </div>
          </div>
        </aside>

        <div className="min-w-0 space-y-4">
          <div className="desk-panel space-y-4 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="title-panel">Available public catalogs</h2>
                <p className="text-sm text-muted">Select a makerspace to view shared equipment.</p>
              </div>
              <span className="eyebrow rounded-full border border-line bg-surface px-3 py-1">
                Standard public portal
              </span>
            </div>
            <form className="flex flex-col gap-3 sm:flex-row sm:items-center" role="search" onSubmit={(event) => event.preventDefault()}>
              <label className="sr-only" htmlFor="makerspace-search">Search makerspaces</label>
              <input
                id="makerspace-search"
                className="desk-input min-w-0 flex-1"
                placeholder="Search by name, code, slug, or location"
                type="search"
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
              />
              {searchInput ? <button className="desk-button shrink-0" type="button" onClick={() => setSearchInput("")}>Clear</button> : null}
              <span className="shrink-0 rounded-lg border border-line bg-surface px-3 py-2 font-mono text-xs text-muted" aria-live="polite">
                {searchQuery ? `${filteredMakerspaces.length}/${totalMakerspaces}` : totalMakerspaces} shown
              </span>
            </form>
          </div>

          {makerspacesQuery.isLoading ? <div className="grid min-h-32 place-items-center desk-panel"><Spinner /></div> : null}
          {makerspacesQuery.isError ? (
            <Card>
              <h2 className="title-panel">Makerspaces are unavailable</h2>
              <p className="mt-2 text-sm leading-6 text-muted">The public makerspace directory could not be loaded.</p>
            </Card>
          ) : null}
          {makerspacesQuery.data && !makerspacesQuery.data.length ? (
            <Card>
              <h2 className="title-panel">No public makerspaces yet</h2>
              <p className="mt-2 text-sm leading-6 text-muted">Public inventory appears here after a makerspace is enabled.</p>
            </Card>
          ) : null}
          {makerspacesQuery.data && makerspacesQuery.data.length > 0 && !filteredMakerspaces.length ? (
            <Card>
              <h2 className="title-panel">No matching makerspaces</h2>
              <p className="mt-2 text-sm leading-6 text-muted">Try another name, makerspace code, URL slug, or location.</p>
            </Card>
          ) : null}

          {filteredMakerspaces.length ? (
            <div className="grid gap-6 sm:grid-cols-2 xl:grid-cols-3">
              {filteredMakerspaces.map((makerspace) => (
                <article key={makerspace.slug} className="group relative flex flex-col rounded-xl border border-line bg-panel shadow-soft transition-transform duration-150 hover:-translate-y-0.5 hover:shadow-soft-lg">
                  <div className="relative h-40 overflow-hidden rounded-t-xl border-b border-line bg-surface">
                    {makerspace.cover_image_url ? (
                      <img src={makerspace.cover_image_url} alt={`${makerspace.name} cover`} loading="lazy" className="h-full w-full object-cover grayscale transition-all duration-500 group-hover:grayscale-0" />
                    ) : <div className="blueprint-bg h-full w-full" />}
                    <span className="absolute left-3 top-3 chip chip-available"><span className="h-2 w-2 rounded-full bg-bg" /> Public</span>
                  </div>
                  <div className="flex min-w-0 flex-1 flex-col p-card-padding p-5">
                    <MakerspaceBrand name={makerspace.name} logoUrl={makerspace.logo_url} size="md" />
                    <MakerspaceMapLink makerspace={makerspace} className="relative z-10 mt-2" locationClassName="break-words font-mono text-xs text-muted" />
                    <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-5">
                      <span className="min-w-0 truncate font-mono text-xs text-muted">{makerspace.public_code}</span>
                      <Link
                        className="inline-flex items-center gap-2 font-mono text-xs font-semibold tracking-tight text-secondary-ink hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus after:absolute after:inset-0 after:content-['']"
                        to={`/m/${makerspace.slug}`}
                        aria-label={`Open ${makerspace.name} catalog`}
                      >
                        Open catalog &rarr;
                      </Link>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          ) : null}
        </div>
      </section>
      <SiteFooter />
    </main>
  );
}
