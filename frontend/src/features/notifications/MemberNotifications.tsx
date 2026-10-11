import { useLiveUpdates } from "../../lib/useLiveUpdates";
import { AnnouncementFeed } from "./AnnouncementFeed";
import { PersonalInbox } from "./PersonalInbox";
import { PreferenceCentre } from "./PreferenceCentre";

export function MemberNotifications({ makerspaceId, features }: { makerspaceId: number; features: string[] }) {
  const inbox = features.includes("notifications.member_inbox");
  useLiveUpdates(inbox);
  return <>
    {inbox && features.includes("membership.broadcasts") ? <AnnouncementFeed key={makerspaceId} makerspaceId={makerspaceId} /> : null}
    {inbox ? <PersonalInbox makerspaceId={makerspaceId} member /> : null}
    {features.includes("notifications.member_preferences") ? <PreferenceCentre key={makerspaceId} makerspaceId={makerspaceId} digests={features.includes("notifications.digests")} /> : null}
  </>;
}
