import { useTrackStore } from "./store";

const LABEL = { connecting: "Connecting…", open: "Live", closed: "Disconnected" } as const;

export function StatusBar() {
  const count = useTrackStore((s) => Object.keys(s.tracks).length);
  const stale = useTrackStore((s) => Object.values(s.tracks).filter((t) => t.stale).length);
  const connection = useTrackStore((s) => s.connection);
  const unseen = useTrackStore((s) => s.unseen);
  return (
    <div className="status">
      <strong>MINI-COP</strong>
      <span className={`dot ${connection}`} />
      <span>{LABEL[connection]}</span>
      <span className="sep">|</span>
      <span>{count} ships{stale > 0 && ` (${stale} stale)`}</span>
      {unseen > 0 && <span className="badge">{unseen} new alert{unseen > 1 ? "s" : ""}</span>}
    </div>
  );
}
