import { SupportContact } from "./SupportContact";
import { Link } from "react-router-dom";

// Shared public footer: copyright + a link out to the in-app About page.
export function SiteFooter({ branding }: { branding?: Record<string, string> }) {
  const year = new Date().getFullYear();
  return (
    <footer className="mt-auto border-t border-line bg-panel">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-5 py-5 text-xs text-muted">
        <p>
          &copy; {year} Space Works &mdash; Open Source Makerspace Manager
        </p>
        <SupportContact branding={branding} />
        <nav className="flex items-center gap-4">
          <Link className="hover:text-ink" to="/about">
            About
          </Link>
          <a
            className="hover:text-ink"
            href="https://github.com/SpaceWorks-HQ/SpaceWorks/blob/main/LICENSE"
            target="_blank"
            rel="noreferrer"
          >
            License
          </a>
        </nav>
      </div>
    </footer>
  );
}
