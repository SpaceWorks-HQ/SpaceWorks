import { Link } from "react-router-dom";

import { SpaceWorksHomeLink, SpaceWorksLogo } from "../components/SpaceWorksLogo";
import { SiteFooter } from "../components/SiteFooter";
import { ThemeToggle } from "../components/ThemeToggle";

export function AboutPage() {
  return (
    <main className="desk-shell flex min-h-screen flex-col">
      <header className="border-b border-line bg-panel">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-5 py-4">
          <SpaceWorksHomeLink className="flex min-w-0 items-center gap-3 text-ink">
            <SpaceWorksLogo className="shrink-0" size={36} />
            <div className="min-w-0">
              <p className="text-sm font-semibold">Space Works</p>
              <p className="eyebrow">Shared equipment portal</p>
            </div>
          </SpaceWorksHomeLink>
          <div className="flex flex-wrap items-center gap-2">
            <ThemeToggle />
            <Link className="desk-button" to="/admin">
              Staff login
            </Link>
          </div>
        </div>
      </header>

      <section className="mx-auto w-full max-w-3xl flex-1 px-5 py-10">
        <p className="eyebrow text-secondary-ink">About</p>
        <h1 className="title-page mt-3">
          Open Source Makerspace Manager
        </h1>
        <div className="mt-5 space-y-4 text-sm leading-6 text-muted">
          <p>
            Space Works is a platform for running community makerspaces &mdash;
            public equipment catalogs, hardware lending with traceable handovers,
            3D-print request queues, and multi-makerspace operations in one place.
          </p>
          <p>
            Each makerspace controls its own inventory, branding, staff, and
            notifications. Visitors browse catalogs and request equipment; staff
            handle approvals, issue and return with evidence, and reporting.
          </p>
          <p className="eyebrow normal-case leading-6">
            Space Works is free and open source software, licensed under the{" "}
            <a
              className="underline hover:text-ink"
              href="https://github.com/SpaceWorks-HQ/SpaceWorks/blob/main/LICENSE"
              target="_blank"
              rel="noreferrer"
            >
              GNU Affero General Public License v3
            </a>
            . Free to use, study, share, and modify under the terms of the AGPL.
          </p>
        </div>

        <div className="mt-8 grid gap-3 sm:grid-cols-2">
          <Link className="desk-panel p-4 transition hover:border-secondary" to="/">
            <h2 className="title-section">Browse makerspaces &rarr;</h2>
            <p className="eyebrow mt-1 normal-case">View public equipment catalogs.</p>
          </Link>
          <Link className="desk-panel p-4 transition hover:border-secondary" to="/admin">
            <h2 className="title-section">Staff login &rarr;</h2>
            <p className="eyebrow mt-1 normal-case">Manage your makerspace.</p>
          </Link>
        </div>
      </section>

      <SiteFooter />
    </main>
  );
}
