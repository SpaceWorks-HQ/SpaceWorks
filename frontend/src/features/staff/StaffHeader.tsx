import { Link } from "react-router-dom";

import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { ThemeToggle } from "../../components/ThemeToggle";
import type { StaffAuthUser } from "../../lib/api";
import type { Makerspace } from "./StaffPanels";

export function StaffHeader({
  activeMakerspace,
  isSuperadmin,
  makerspaces,
  onSignOut,
  onSwitchMakerspace,
  roleName,
  selected,
  setSelected,
  singleTenantLocked,
  user,
}: {
  activeMakerspace?: Makerspace;
  isSuperadmin: boolean;
  makerspaces: Makerspace[];
  onSignOut: () => void;
  onSwitchMakerspace: () => void;
  roleName?: string;
  selected: number | null;
  setSelected: (id: number | null) => void;
  singleTenantLocked: boolean;
  user: StaffAuthUser;
}) {
  const publicInventoryPath = activeMakerspace
    ? singleTenantLocked ? "/" : "/m/" + activeMakerspace.slug
    : null;

  return (
    <header className="border-b border-line bg-surface px-5 py-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <SpaceWorksBadge className="shrink-0" />
          <div className="min-w-0">
            <p className="eyebrow truncate text-accent-ink">
              {activeMakerspace?.public_code ?? activeMakerspace?.slug ?? "No workspace"}
            </p>
            <h1 className="title-page break-words uppercase">
              {activeMakerspace?.name ?? "Inventory Control"}
            </h1>
            {roleName ? <p className="eyebrow truncate">{roleName}</p> : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!singleTenantLocked && makerspaces.length > 1 ? (
            <select
              className="desk-input"
              aria-label="Active makerspace"
              value={selected ?? ""}
              onChange={(event) => setSelected(Number(event.target.value))}
            >
              {makerspaces.map((makerspace) => (
                <option key={makerspace.id} value={makerspace.id}>
                  {makerspace.name}
                </option>
              ))}
            </select>
          ) : null}
          <span className="eyebrow max-w-full truncate rounded-lg border border-line bg-panel px-3 py-2 sm:max-w-56">
            {user.username}
          </span>
          {publicInventoryPath ? (
            <Link className="desk-button" to={publicInventoryPath}>
              Public inventory
            </Link>
          ) : null}
          {isSuperadmin && !singleTenantLocked ? (
            <button className="desk-button-primary" type="button" onClick={onSwitchMakerspace}>
              Switch makerspace
            </button>
          ) : null}
          <ThemeToggle />
          <button className="desk-button-ghost" type="button" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}
