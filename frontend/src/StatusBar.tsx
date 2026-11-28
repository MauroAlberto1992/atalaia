import { useTrackStore } from "./store";

const LABEL = { connecting: "Connecting…", open: "Live", closed: "Disconnected" } as const;

export function StatusBar() {
  const count = useTrackStore((s) => Object.keys(s.tracks).length);
  const stale = useTrackStore((s) => Object.values(s.tracks).filter((t) => t.stale).length);
  const connection = useTrackStore((s) => s.connection);
  const unseen = useTrackStore((s) => s.unseen);
  const sensorOn = useTrackStore((s) => s.sensor !== null);
  const darkCount = useTrackStore((s) => s.dark.filter((d) => d.confirmed && d.possible_mmsi === null).length);
  const showDetections = useTrackStore((s) => s.showDetections);
  const toggleDetections = useTrackStore((s) => s.toggleDetections);
  const showDepth = useTrackStore((s) => s.showDepth);
  const toggleDepth = useTrackStore((s) => s.toggleDepth);
  return (
    <div className="status">
      <strong>MINI-COP</strong>
      <span className={`dot ${connection}`} />
      <span>{LABEL[connection]}</span>
      <span className="sep">|</span>
      <span>{count} ships{stale > 0 && ` (${stale} stale)`}</span>
      {sensorOn && (
        <>
          <span className="sep">|</span>
          {/* Always labelled: simulated contacts must never pass for real ones. */}
          <span className="sim">SIMULATED sensor</span>
          {darkCount > 0 && <span className="dark-count">{darkCount} dark</span>}
          <button className="chip" aria-pressed={showDetections} onClick={toggleDetections}>
            Detections
          </button>
        </>
      )}
      <button className="chip" aria-pressed={showDepth} onClick={toggleDepth} title="Sea depth, EMODnet (not for navigation)">
        Depth
      </button>
      {unseen > 0 && <span className="badge">{unseen} new alert{unseen > 1 ? "s" : ""}</span>}
    </div>
  );
}
