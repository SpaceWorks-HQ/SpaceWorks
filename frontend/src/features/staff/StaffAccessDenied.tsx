import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { ThemeToggle } from "../../components/ThemeToggle";

export function StaffAccessDenied({ makerspaceName, onSignOut }: { makerspaceName?: string; onSignOut: () => void }) {
  return (
    <main className="desk-shell grid place-items-center px-5">
      <section className="desk-panel w-full max-w-md bg-warn p-6 text-on-warn dark:bg-warn/15 dark:text-warn-ink">
        <SpaceWorksBadge className="mb-5" />
        <p className="eyebrow text-inherit">Access denied</p>
        <h1 className="title-page mt-2 text-inherit">You do not have access to this makerspace.</h1>
        <p className="mt-2 text-sm leading-6">
          This branded admin dashboard is locked to {makerspaceName ?? "this makerspace"}. Sign in with an
          account that has a membership for it.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <ThemeToggle />
          <button className="desk-button-ghost text-inherit hover:bg-warn/15" type="button" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      </section>
    </main>
  );
}
