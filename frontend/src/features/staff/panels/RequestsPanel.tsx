import { Queues } from "./Queues";
import { type Makerspace } from "./shared";
import { KioskReplayRecoveryPanel } from "../../kiosk/KioskReplayRecoveryPanel";

export function RequestsPanel({ makerspace, guestOnly, canSeeHardware, canViewAudit }: { makerspace: Makerspace; guestOnly: boolean; canSeeHardware: boolean; canViewAudit: boolean }) {
  return canSeeHardware ? <div className="grid gap-4"><Queues makerspace={makerspace} guestOnly={guestOnly} canViewAudit={canViewAudit} /><KioskReplayRecoveryPanel makerspaceId={makerspace.id} /></div> : <p className="text-sm text-muted">Machine-service queues are managed from Machines.</p>;
}
