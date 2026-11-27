import { useEffect, useState } from "react";
import { useTrackStore } from "./store";

type Kind = "restricted" | "watch";

// "Draw area" (phase 16): click points on the map, close the area, name it.
// The backend validates (crossing edges, outside the monitored area, name
// taken) and its message is shown as is.
export function DrawArea() {
  const drawing = useTrackStore((s) => s.drawing);
  const points = useTrackStore((s) => s.draft.length);
  const closed = useTrackStore((s) => s.draftClosed);
  const [name, setName] = useState("");
  const [kind, setKind] = useState<Kind>("watch");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Esc cancels the drawing.
  useEffect(() => {
    if (!drawing) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") useTrackStore.getState().cancelDraw();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawing]);

  const start = () => {
    setName("");
    setError(null);
    setNotice(null);
    useTrackStore.getState().startDraw();
  };

  const save = () => {
    const { draft } = useTrackStore.getState();
    setSaving(true);
    setError(null);
    fetch("/api/zones", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim(), kind, polygon: draft }),
    })
      .then(async (r) => {
        const body = (await r.json().catch(() => null)) as
          | { saved?: boolean; detail?: string | { msg: string }[] }
          | null;
        if (!r.ok) {
          const d = body?.detail;
          throw new Error(typeof d === "string" ? d : d?.[0]?.msg ?? `HTTP ${r.status}`);
        }
        setNotice(
          body?.saved
            ? `"${name.trim()}" created. Ships already inside are not alerted.`
            : `"${name.trim()}" created, but not saved (no database): lost on restart.`,
        );
        useTrackStore.getState().cancelDraw(); // the map shows it when /live says so
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setSaving(false));
  };

  if (!drawing) {
    return (
      <div className="draw-area">
        <button className="home-button" onClick={start}>
          ✎ Draw area
        </button>
        {notice && <p className="note">{notice}</p>}
      </div>
    );
  }

  return (
    <div className="draw-area panel-box">
      {!closed ? (
        <p className="note">
          Click on the map to add points ({points} so far). Double-click, or click the first point,
          to close the area. Esc cancels.
        </p>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            save();
          }}
        >
          <label>
            Name{" "}
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={60} autoFocus required />
          </label>
          <div className="sorts" role="group" aria-label="Area kind">
            {(["watch", "restricted"] as const).map((k) => (
              <button key={k} type="button" className="chip" aria-pressed={kind === k} onClick={() => setKind(k)}>
                {k}
              </button>
            ))}
          </div>
          <p className="note">Alerts when a ship or a dark contact enters. Ships already inside are not alerted.</p>
          {error && <p className="note error">{error}</p>}
          <button type="submit" className="home-button" disabled={saving || !name.trim()}>
            Save
          </button>{" "}
          <button type="button" className="home-button" onClick={() => useTrackStore.getState().cancelDraw()}>
            Cancel
          </button>
        </form>
      )}
      {!closed && (
        <button className="home-button" onClick={() => useTrackStore.getState().cancelDraw()}>
          Cancel
        </button>
      )}
    </div>
  );
}
