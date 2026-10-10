import { Link, useParams } from "react-router-dom";

import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { ThemeToggle } from "../../components/ThemeToggle";
import { PublicInventoryPage } from "../inventory/PublicInventoryPage";

// The central `/kiosk/:slug` public desk, moved unchanged from staff/PlatformApps.tsx.
// Station kiosks live at `/m/:slug/kiosk/:stationToken` and never collide with it.
export function PublicDeskKioskPage() {
  const { slug } = useParams();
  return (
    <main className="desk-shell">
      <header className="border-b border-line bg-panel">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-3">
          <div>
            <SpaceWorksBadge className="mb-3" />
            <p className="text-xs font-semibold tracking-wide text-accent-ink">
              Kiosk
            </p>
            <h1 className="text-xl font-bold text-ink">Public desk</h1>
          </div>
          <div className="flex gap-2">
            <ThemeToggle />
            <Link className="desk-button" to={`/m/${slug ?? ""}`}>
              Catalog
            </Link>
          </div>
        </div>
      </header>
      <PublicInventoryPage />
    </main>
  );
}
