import { useEffect, useState } from "react";
import { memberScope } from "../../lib/pwaScopes";

type InstallEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> };

export function MemberInstall({ name }: { name: string }) {
  const [prompt, setPrompt] = useState<InstallEvent | null>(null);
  useEffect(() => {
    const scope = memberScope(window.location.pathname);
    if (!scope || !("serviceWorker" in navigator) || !import.meta.env.PROD) return;
    const link = document.createElement("link"); link.rel = "manifest";
    link.href = `${scope}/manifest.webmanifest?name=${encodeURIComponent(name)}`;
    const attach = () => {
      if (navigator.serviceWorker.controller?.scriptURL.endsWith("/member-sw.js")) {
        link.remove(); document.head.append(link);
      }
    };
    attach(); navigator.serviceWorker.addEventListener("controllerchange", attach);
    const onPrompt = (event: Event) => { event.preventDefault(); setPrompt(event as InstallEvent); };
    const installed = () => setPrompt(null);
    window.addEventListener("beforeinstallprompt", onPrompt); window.addEventListener("appinstalled", installed);
    return () => { link.remove(); navigator.serviceWorker.removeEventListener("controllerchange", attach); window.removeEventListener("beforeinstallprompt", onPrompt); window.removeEventListener("appinstalled", installed); };
  }, [name]);
  return <section className="desk-panel p-4"><h2 className="title-panel">Keep your member card handy</h2><p className="mt-2 text-sm text-muted">Install this member area from your browser menu. On iPhone, use Share → Add to Home Screen. Save your card below to read it offline on this device.</p>{prompt ? <button className="desk-button-secondary mt-3" type="button" onClick={() => { void prompt.prompt().then(() => prompt.userChoice).catch(() => undefined).finally(() => setPrompt(null)); }}>Install member area</button> : null}</section>;
}
