import { PersonalInbox } from "../../notifications/PersonalInbox";
import type { Makerspace } from "./shared";

export function NotificationInbox({ makerspace }: { makerspace: Makerspace }) {
  return <PersonalInbox makerspaceId={makerspace.id} />;
}
