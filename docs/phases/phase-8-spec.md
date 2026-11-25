# Phase 8 spec — Docker

Status: approved.

## Goal
Run the whole Mini-COP with one command (`docker compose up`) on any machine
with Docker, with no local Python or Node setup. Also proves the service is
deployable, not just a dev setup.

## Scope
1. **`backend/Dockerfile`**
   - Base: `python:3.12-slim`, pinned (not `latest`).
   - Installs the package, without dev tools.
   - Runs as a **non-root** user, with `uvicorn` listening on `0.0.0.0:8000`.
   - `HEALTHCHECK` on `GET /health`, so Docker knows when the service is up.
2. **`frontend/Dockerfile`**, multi-stage:
   - build stage on `node:22-alpine` (`npm ci` + `vite build`);
   - runtime stage on `nginx:1.28-alpine`, serving only the static files (no Node in the final image).
3. **`frontend/nginx.conf`**: serves the app and proxies `/api/*` to the backend (prefix stripped) and `/live` with WebSocket upgrade headers.
   This is the same routing the Vite dev server does, so the frontend code doesn't change.
4. **`docker-compose.yml`** at the repo root:
   - `backend` reads `.env` at runtime;
   - `frontend` is published on `http://localhost:8080`;
   - `frontend` waits for the backend's healthcheck;
   - both use `restart: unless-stopped`.
5. **`.dockerignore`** files that keep `.env`, `.venv`, `node_modules` and caches out of the images.
   **The API key never enters an image**; it is only passed at runtime.
6. **Guardrails**
   - `hadolint` (Dockerfile linter) in pre-commit.
   - A CI job that builds both images, starts the stack with a dummy API key, and smoke-tests it through nginx:
     - `/` returns the app;
     - `/api/health` answers;
     - `/live` accepts a WebSocket and sends a snapshot.
   - With a dummy key, aisstream rejects the subscription and the service keeps retrying, but the API still answers. That is enough to prove the wiring.
7. **Docs**: "Run with Docker" in the README, `docs/phases/phase-8.md`, and a `CLAUDE.md` update.

## Out of scope
- Deploying to a server or cloud, TLS, and a container registry.
- Database (next candidate).
- Hot reload in containers; development keeps using `uvicorn --reload` and `npm run dev`.

## Decisions to confirm
- **Port 8080 for the app.** It avoids clashing with `npm run dev` (5173) and a local backend (8000). The backend is not published to the host; only nginx talks to it.

## Acceptance
- `docker compose up --build` on a clean machine with a real `.env` shows live ships at `http://localhost:8080`.
- CI builds the images and the smoke test passes.
- `docker history` / an image inspect shows no `.env` in either image.
- Pre-commit (including hadolint) passes.
