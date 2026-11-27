// Ship icons drawn on a canvas at startup, so there are no image files to load.
// Pixel ratio 2 keeps them sharp on retina screens.

const SIZE = 32;
const RATIO = 2;

function draw(paint: (ctx: CanvasRenderingContext2D, s: number) => void): ImageData {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = SIZE * RATIO;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("2D canvas not available");
  ctx.scale(RATIO, RATIO);
  paint(ctx, SIZE);
  return ctx.getImageData(0, 0, canvas.width, canvas.height);
}

const LIVE_FILL = "#38bdf8"; // Class A (ships): blue
// Class B (small craft): green, lighter than the protected-zone green (#22c55e)
// so the two don't read as the same thing.
const CLASS_B_FILL = "#4ade80";
const STALE_FILL = "#94a3b8"; // grey: ship has gone silent (either class)

function fillFor(stale: boolean, classB: boolean): string {
  if (stale) return STALE_FILL;
  return classB ? CLASS_B_FILL : LIVE_FILL;
}
const STROKE = "#0c1220";

// Arrow pointing up (north); MapLibre rotates it by COG.
export const movingIcon = (stale = false, classB = false) =>
  draw((ctx, s) => {
    ctx.beginPath();
    ctx.moveTo(s / 2, 3);
    ctx.lineTo(s - 8, s - 5);
    ctx.lineTo(s / 2, s - 11);
    ctx.lineTo(8, s - 5);
    ctx.closePath();
    ctx.fillStyle = fillFor(stale, classB);
    ctx.strokeStyle = STROKE;
    ctx.lineWidth = 2;
    ctx.fill();
    ctx.stroke();
  });

// Circle for ships that are not moving: a direction would be meaningless.
export const stoppedIcon = (stale = false, classB = false) =>
  draw((ctx, s) => {
    ctx.beginPath();
    ctx.arc(s / 2, s / 2, 6, 0, Math.PI * 2);
    ctx.fillStyle = fillFor(stale, classB);
    ctx.strokeStyle = STROKE;
    ctx.lineWidth = 2;
    ctx.fill();
    ctx.stroke();
  });

// Chevron (">" turned to point north) for recorded route points: shows the
// direction of travel. Rotated by the bearing to the next report.
export const chevronIcon = () =>
  draw((ctx, s) => {
    ctx.beginPath();
    ctx.moveTo(s / 2 - 6, s / 2 + 4);
    ctx.lineTo(s / 2, s / 2 - 4);
    ctx.lineTo(s / 2 + 6, s / 2 + 4);
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = STROKE; // dark outline first, for contrast on any basemap
    ctx.lineWidth = 5;
    ctx.stroke();
    ctx.strokeStyle = "#facc15"; // route yellow
    ctx.lineWidth = 2.5;
    ctx.stroke();
  });

// Dark vessel (sensor contact with no AIS): red diamond.
export const darkIcon = () =>
  draw((ctx, s) => {
    ctx.beginPath();
    ctx.moveTo(s / 2, s / 2 - 8);
    ctx.lineTo(s / 2 + 7, s / 2);
    ctx.lineTo(s / 2, s / 2 + 8);
    ctx.lineTo(s / 2 - 7, s / 2);
    ctx.closePath();
    ctx.fillStyle = "#ef4444";
    ctx.strokeStyle = "#fecaca";
    ctx.lineWidth = 1.5;
    ctx.fill();
    ctx.stroke();
  });

// The (SIMULATED) patrol drone: white cross in a ring.
export const droneIcon = () =>
  draw((ctx, s) => {
    const c = s / 2;
    ctx.strokeStyle = "#0c1220";
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.moveTo(c - 8, c); ctx.lineTo(c + 8, c); ctx.moveTo(c, c - 8); ctx.lineTo(c, c + 8);
    ctx.stroke();
    ctx.strokeStyle = "#f8fafc";
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(c, c, 4, 0, Math.PI * 2);
    ctx.fillStyle = "#f8fafc";
    ctx.fill();
  });

export const ICON_PIXEL_RATIO = RATIO;
