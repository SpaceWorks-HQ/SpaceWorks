import { useLiveUpdates } from "../../lib/useLiveUpdates";
import { PersonalInbox } from "./PersonalInbox";
import { PreferenceCentre } from "./PreferenceCentre";

export function MemberNotifications({ makerspaceId, features }: { makerspaceId: number; features: string[] }) {
  const inbox = features.includes("notifications.member_inbox");
  useLiveUpdates(inbox);
  return <>
    {inbox ? <PersonalInbox makerspaceId={makerspaceId} member /> : null}
    {features.includes("notifications.member_preferences") ? <PreferenceCentre makerspaceId={makerspaceId} /> : null}
  </>;
}
