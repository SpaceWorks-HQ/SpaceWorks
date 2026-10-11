import { useEffect, useState } from "react";
import type { MemberCard } from "./api";
import { forgetOfflineCard, readOfflineCard, saveOfflineCard } from "./offlineCard";

export function OfflineCardSave({ card, space, checkedAt }: { card: MemberCard; space: string; checkedAt: number }) {
  const [saved, setSaved] = useState(() => readOfflineCard()?.id === card.id);
  const [offlineReady, setOfflineReady] = useState(() => navigator.serviceWorker?.controller?.scriptURL.endsWith("/member-sw.js") ?? false);
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    const workers = navigator.serviceWorker;
    const ready = () => setOfflineReady(workers.controller?.scriptURL.endsWith("/member-sw.js") ?? false);
    ready(); workers.addEventListener("controllerchange", ready);
    return () => workers.removeEventListener("controllerchange", ready);
  }, []);
  const projection = () => ({ id: card.id, name: card.printed_name, number: card.card_number, space, qr: card.qr_image ?? "", savedAt: new Date(checkedAt || Date.now()).toISOString() });
  useEffect(() => {
    const old = readOfflineCard();
    if (!card.is_active || !card.qr_active || (old && old.id !== card.id)) { forgetOfflineCard(); setSaved(false); }
    else if (old) { saveOfflineCard(projection()); setSaved(Boolean(readOfflineCard())); }
  }, [card, space, checkedAt]);
  return <div className="mt-4 border-t border-line pt-4">
    {card.qr_image && card.is_active && card.qr_active ? <img className="w-48 max-w-full" src={card.qr_image} alt="Your member card QR" /> : null}
    <p className="mt-2 text-sm text-muted">Save only your card name, number and QR on this device. Offline copies are last-known and cannot prove current access. Use a personal device.</p>
    {!offlineReady ? <p className="mt-2 text-sm text-muted">Offline access is preparing. It needs a supported browser and a secure connection.</p> : null}
    <button className="desk-button-secondary mt-3" type="button" disabled={!saved && (!offlineReady || !card.is_active || !card.qr_active || !card.qr_image)} onClick={() => {
      if (saved) { forgetOfflineCard(); setSaved(false); }
      else { saveOfflineCard(projection()); setSaved(Boolean(readOfflineCard())); }
    }}>{saved ? "Forget offline card" : "Save card for offline use"}</button>
    {saved ? <p role="status" className="mt-2 text-sm text-muted">Last-known card saved on this device.</p> : null}
  </div>;
}
