import { useEffect } from "react";
import { connectLive } from "./live";
import { MapView } from "./MapView";
import { ShipPanel } from "./ShipPanel";
import { StatusBar } from "./StatusBar";

export function App() {
  useEffect(() => connectLive(), []); // returns the cleanup that closes the socket
  return (
    <>
      <MapView />
      <StatusBar />
      <ShipPanel />
    </>
  );
}
