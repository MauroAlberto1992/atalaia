import { useTrackStore } from "./store";
import type { LiveMessage } from "./types";

const RECONNECT_DELAY_MS = 3000;

// Opens WS /live and feeds the store. Reconnects forever; each new connection
// starts with a snapshot, so the state is rebuilt without any extra logic.
// Returns a function that stops it (used by React's effect cleanup).
export function connectLive(): () => void {
  const { applyLive, setConnection } = useTrackStore.getState();
  let ws: WebSocket | null = null;
  let retryTimer: number | undefined;
  let stopped = false;

  const open = () => {
    setConnection("connecting");
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${scheme}://${location.host}/live`);
    ws.onopen = () => setConnection("open");
    ws.onmessage = (e) => applyLive(JSON.parse(e.data) as LiveMessage);
    ws.onclose = () => {
      setConnection("closed");
      if (!stopped) retryTimer = window.setTimeout(open, RECONNECT_DELAY_MS);
    };
  };

  open();
  return () => {
    stopped = true;
    window.clearTimeout(retryTimer);
    ws?.close();
  };
}
