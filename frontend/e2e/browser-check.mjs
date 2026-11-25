// Browser check of the production build: does the map actually draw ships?
//
// Unit tests, the build and the HTTP smoke test all passed while the
// production map was blank (MapLibre's web worker was missing from the build).
// Only a real browser shows that, so this runs in CI against the Docker stack.
//
// Usage: node e2e/browser-check.mjs [base_url]   (default http://localhost:8080)
// Fake ships are injected by intercepting /live, so no AIS feed is needed.
// The basemap style is replaced by a plain background so the check doesn't
// depend on an external tile server.
import { chromium } from "playwright";

const base = process.argv[2] ?? "http://localhost:8080";

const ship = (mmsi, lat, lon) => ({
  mmsi, ship_name: `TEST ${mmsi}`, latitude: lat, longitude: lon, sog: 8, cog: 90,
  true_heading: 511, navigational_status: 0, last_seen: new Date().toISOString(),
  stale: false, distance_nm: 0, avg_speed_kn: 0,
});

// CI uses Playwright's own Chromium; a local machine may point to another one.
const browser = await chromium.launch(
  process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
);
const page = await browser.newPage({ viewport: { width: 1000, height: 700 } });

const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });

await page.route("**/styles/**", (r) =>
  r.fulfill({ json: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": "#0f1b2d" } }] } }),
);
await page.routeWebSocket(/\/live$/, (ws) => {
  ws.send(JSON.stringify({
    type: "snapshot",
    alerts: [],
    tracks: [ship(1, 37.0, -8.6), ship(2, 36.95, -8.2), ship(3, 37.05, -7.9)],
  }));
});

await page.goto(base);
await page.waitForTimeout(4000);

// Count pixels of the ship colour (#38bdf8, LIVE_FILL in shipIcons.ts) in a
// screenshot of the map canvas.
const shot = await page.locator("canvas.maplibregl-canvas").screenshot();
const shipPixels = await page.evaluate(async (b64) => {
  const img = new Image();
  img.src = `data:image/png;base64,${b64}`;
  await img.decode();
  const c = new OffscreenCanvas(img.width, img.height);
  const ctx = c.getContext("2d");
  ctx.drawImage(img, 0, 0);
  const d = ctx.getImageData(0, 0, img.width, img.height).data;
  let n = 0;
  for (let i = 0; i < d.length; i += 4) {
    if (Math.abs(d[i] - 0x38) < 12 && Math.abs(d[i + 1] - 0xbd) < 12 && Math.abs(d[i + 2] - 0xf8) < 12) n++;
  }
  return n;
}, shot.toString("base64"));
await browser.close();

const { status } = await fetch(`${base}/`);
console.log(`page status ${status}, ship-coloured pixels: ${shipPixels}, errors: ${errors.length}`);
for (const e of errors) console.log(`  error: ${e.slice(0, 200)}`);
if (shipPixels < 50) {
  console.error("FAIL: no ships drawn on the map");
  process.exit(1);
}
if (errors.length > 0) {
  console.error("FAIL: errors in the browser console");
  process.exit(1);
}
console.log("ok  map draws ships, no console errors");
