import { PersonalInbox } from "../../notifications/PersonalInbox";
import { BroadcastComposer } from "../BroadcastComposer";
import type { Makerspace } from "./shared";

export function NotificationInbox({ makerspace, canManageMembers = false }: { makerspace: Makerspace; canManageMembers?: boolean }) {
  return <>
    {canManageMembers && makerspace.enabled_features?.includes("membership.broadcasts") ? <BroadcastComposer makerspaceId={makerspace.id} /> : null}
    <PersonalInbox makerspaceId={makerspace.id} />
  </>;
}
