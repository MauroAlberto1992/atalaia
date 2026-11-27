import { beforeEach, describe, expect, it } from "vitest";
import { useTrackStore } from "./store";

const s = () => useTrackStore.getState();

describe("drawing an area", () => {
  beforeEach(() => s().cancelDraw());

  it("collects points only while drawing", () => {
    s().addDraftPoint([36.9, -8.5]);
    expect(s().draft).toEqual([]);
    s().startDraw();
    s().addDraftPoint([36.9, -8.5]);
    s().addDraftPoint([36.9, -8.4]);
    expect(s().draft).toHaveLength(2);
  });

  it("closes only with 3 points or more, then takes no more points", () => {
    s().startDraw();
    s().addDraftPoint([36.9, -8.5]);
    s().addDraftPoint([36.9, -8.4]);
    s().closeDraft();
    expect(s().draftClosed).toBe(false);
    s().addDraftPoint([36.8, -8.45]);
    s().closeDraft();
    expect(s().draftClosed).toBe(true);
    s().addDraftPoint([36.7, -8.45]);
    expect(s().draft).toHaveLength(3);
  });

  it("a 'zones' message asks the map to refetch the areas", () => {
    const before = s().zonesVersion;
    s().applyLive({ type: "zones" });
    expect(s().zonesVersion).toBe(before + 1);
  });
});
