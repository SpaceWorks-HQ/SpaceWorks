import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { connectLiveUpdates } from "./live";

// One stream per signed-in staff session. Mounted from the session hook so it lives exactly
// as long as the authenticated console does, and pauses while the tab is hidden: a
// background tab does not need to refetch on every change, and it reconnects on return.
export function useLiveUpdates(enabled: boolean) {
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!enabled) return;
    let stop: (() => void) | null = null;
    const start = () => {
      if (!stop && document.visibilityState !== "hidden") stop = connectLiveUpdates(queryClient);
    };
    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        stop?.();
        stop = null;
      } else {
        start();
      }
    };
    start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      stop?.();
    };
  }, [enabled, queryClient]);
}
