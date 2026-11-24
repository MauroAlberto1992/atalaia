# Phase 3 spec — React map

> Reconstructed after the fact from the approved plan in the working session. From phase 7 on, specs are written and approved before any code.

## Goal
A live map in the browser.

## Scope
- Vite + React + TypeScript, Zustand store fed by `/live` with reconnection.
- MapLibre with one GeoJSON source; arrows rotated by COG.
- Click a ship to see its details; status bar.
- Store tests.

## Out of scope
Routes, zones, stale styling.

## Acceptance
- Live ships appear on a dark basemap.
- Clicking a ship opens its details.
