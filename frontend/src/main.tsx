import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import "./index.css";
import { cleanupLegacyAccessToken } from "./lib/api";
import { queryClient } from "./lib/queryClient";
import { TenantProvider } from "./lib/tenant";
import { initializeTheme } from "./lib/theme";
import { pruneExpiredOfflineStates } from "./features/staff/eventCheckInOfflineStore";
import { listQueues } from "./features/kiosk/offlineQueueStore";
import { replayQueue } from "./features/kiosk/kioskReplayClient";

initializeTheme();
cleanupLegacyAccessToken();
void pruneExpiredOfflineStates().catch(() => undefined);
void listQueues().then(async (queues) => {
  for (const queue of queues) await replayQueue(queue.scope);
}).catch(() => undefined);
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/sw.js", { updateViaCache: "none" }).catch(() => undefined);
  });
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <TenantProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </TenantProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
