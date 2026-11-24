import { useTrackStore } from "./store";

const LABEL = { connecting: "Connecting…", open: "Live", closed: "Disconnected" } as const;

export function StatusBar() {
  const count = useTrackStore((s) => Object.keys(s.tracks).length);
  const connection = useTrackStore((s) => s.connection);
  return (
    <div className="status">
      <strong>MINI-COP</strong>
      <span className={`dot ${connection}`} />
      <span>{LABEL[connection]}</span>
      <span className="sep">|</span>
      <span>{count} ships</span>
    </div>
  );
}
