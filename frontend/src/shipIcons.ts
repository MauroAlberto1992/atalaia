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

const LIVE_FILL = "#38bdf8";
const STALE_FILL = "#94a3b8"; // grey: ship has gone silent
const STROKE = "#0c1220";

// Arrow pointing up (north); MapLibre rotates it by COG.
export const movingIcon = (stale = false) =>
  draw((ctx, s) => {
    ctx.beginPath();
    ctx.moveTo(s / 2, 3);
    ctx.lineTo(s - 8, s - 5);
    ctx.lineTo(s / 2, s - 11);
    ctx.lineTo(8, s - 5);
    ctx.closePath();
    ctx.fillStyle = stale ? STALE_FILL : LIVE_FILL;
    ctx.strokeStyle = STROKE;
    ctx.lineWidth = 2;
    ctx.fill();
    ctx.stroke();
  });

// Circle for ships that are not moving: a direction would be meaningless.
export const stoppedIcon = (stale = false) =>
  draw((ctx, s) => {
    ctx.beginPath();
    ctx.arc(s / 2, s / 2, 6, 0, Math.PI * 2);
    ctx.fillStyle = stale ? STALE_FILL : LIVE_FILL;
    ctx.strokeStyle = STROKE;
    ctx.lineWidth = 2;
    ctx.fill();
    ctx.stroke();
  });

export const ICON_PIXEL_RATIO = RATIO;
