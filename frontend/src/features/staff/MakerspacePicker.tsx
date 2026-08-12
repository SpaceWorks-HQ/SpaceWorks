import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { ThemeToggle } from "../../components/ThemeToggle";
import { Badge } from "../../components/ui";
import type { Makerspace } from "./StaffPanels";

/**
 * Superadmin entry screen: the superadmin operates one makerspace at a time, so
 * before the console loads they explicitly pick which makerspace to operate. The
 * chosen id then scopes every staff API call (the backend already takes a
 * makerspace_id per request). Reachable again via "Switch makerspace" in the shell.
 */
export function MakerspacePicker({
  makerspaces,
  loading,
  username,
  onSelect,
  onSignOut,
}: {
  makerspaces: Makerspace[];
  loading: boolean;
  username: string;
  onSelect: (id: number) => void;
  onSignOut: () => void;
}) {
  return (
    <main className="desk-shell min-h-screen px-5 py-10">
      <div className="mx-auto w-full max-w-3xl">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <SpaceWorksBadge className="mb-3" />
            <p className="text-xs font-semibold tracking-wide text-accent-ink">Super Admin</p>
            <h1 className="text-2xl font-bold text-ink">Choose a makerspace to operate</h1>
            <p className="mt-1 text-sm text-muted">Signed in as {username}. Pick a makerspace to manage its operations.</p>
          </div>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <button className="desk-button" type="button" onClick={onSignOut}>
              Sign out
            </button>
          </div>
        </div>

        {loading ? (
          <p className="text-sm text-muted">Loading makerspaces…</p>
        ) : !makerspaces.length ? (
          <div className="desk-panel bg-warn p-6 text-on-warn dark:bg-[#332b00] dark:text-[#fcdf46]">
            <p className="text-sm">No makerspaces exist yet. Create one from the Django control plane.</p>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {makerspaces.map((makerspace) => (
              <button
                key={makerspace.id}
                type="button"
                onClick={() => onSelect(makerspace.id)}
                className="desk-panel flex flex-col items-start gap-1 p-4 text-left transition hover:border-accent"
              >
                <span className="text-xs font-semibold uppercase tracking-wide text-accent-ink">
                  {makerspace.public_code ?? makerspace.slug}
                </span>
                <span className="text-lg font-semibold text-ink">{makerspace.name}</span>
                {makerspace.superadmin_access_enabled === false ? (
                  <span className="mt-1">
                    <Badge tone="warn">Superadmin access: Off</Badge>
                  </span>
                ) : null}
                <span className="mt-2 text-xs text-muted">Operate this makerspace →</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
