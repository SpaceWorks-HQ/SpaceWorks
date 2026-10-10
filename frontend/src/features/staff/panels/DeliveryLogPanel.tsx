import { DeliveryLogScreen } from "../../notifications/DeliveryLogScreen";
import type { Makerspace } from "./shared";

export function DeliveryLogPanel({ makerspace }: { makerspace: Makerspace }) {
  return <DeliveryLogScreen makerspaceId={makerspace.id} />;
}
