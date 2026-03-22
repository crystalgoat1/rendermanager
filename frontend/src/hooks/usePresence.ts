import { useEffect } from "preact/hooks";
import { useApi } from "./useApi";
import { useSession } from "./useSession";

/**
 * Sends a lightweight presence ping to the server every 30 s while the
 * browser tab is visible.  Pauses automatically when the tab is hidden.
 *
 * This lets the agent know someone is watching the dashboard so it can
 * poll more frequently and stream live previews.
 */
export function usePresence() {
  const { apiFetch } = useApi();
  const { session } = useSession();

  useEffect(() => {
    if (!session) return;

    let intervalId: ReturnType<typeof setInterval> | null = null;

    function sendPing() {
      apiFetch("/api/presence", { method: "POST" }).catch(() => {});
    }

    function start() {
      sendPing();
      intervalId = setInterval(sendPing, 30_000);
    }

    function stop() {
      if (intervalId) {
        clearInterval(intervalId);
        intervalId = null;
      }
    }

    function onVisibilityChange() {
      if (document.visibilityState === "visible") {
        start();
      } else {
        stop();
      }
    }

    // Start immediately if tab is already visible
    if (document.visibilityState === "visible") {
      start();
    }

    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      document.removeEventListener("visibilitychange", onVisibilityChange);
      stop();
    };
  }, [!!session]);
}
