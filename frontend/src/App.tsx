import { useEffect } from "react";
import { AlertPanel } from "./AlertPanel";
import { DrawArea } from "./DrawArea";
import { connectLive } from "./live";
import { MapView } from "./MapView";
import { RecentShips } from "./RecentShips";
import { ShipPanel } from "./ShipPanel";
import { StatusBar } from "./StatusBar";
import { useTrackStore } from "./store";

export function App() {
  useEffect(() => connectLive(), []); // returns the cleanup that closes the socket
  return (
    <>
      <MapView />
      <StatusBar />
      <ShipPanel />
      <AlertPanel />
      <div className="left-stack">
        <RecentShips />
        <button className="home-button" onClick={() => useTrackStore.getState().goHome()}>
          ⌂ Whole area
        </button>
        <DrawArea />
      </div>
    </>
  );
}
