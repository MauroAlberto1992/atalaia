# Phase 8 — Docker

## Done
- **`backend/Dockerfile`**
  - Base: `python:3.12-slim`.
  - Runs as the unprivileged uid `10001`.
  - `HEALTHCHECK` on `/health`, using the Python stdlib so no curl is needed.
- **`frontend/Dockerfile`**, multi-stage: `node:22-alpine` builds the app, and `nginx:1.28-alpine` serves `dist/`. The runtime image has no Node.
- **`frontend/nginx.conf`**: serves the app and proxies `/api/*` (prefix stripped) and `/live` (WebSocket) to the backend, the same routing as the Vite dev server.
- **`docker-compose.yml`**
  - The frontend is on `http://localhost:8080`.
  - The backend is not published to the host.
  - The frontend waits for the backend to be healthy.
  - The API key comes from `.env` at runtime.
- **`.dockerignore`** for both images: `.env`, venvs, `node_modules` and caches never enter the build context.
- **`scripts/smoke_test.py`**: an end-to-end check through nginx of `/`, `/api/health` and the `/live` snapshot.
- **Guardrails**
  - `frontend/e2e/browser-check.mjs`: headless Chromium against the production stack, with fake ships injected into `/live`; it asserts that ships are drawn and that the console has no errors. Added after the blank-map bug.
  - `hadolint` in pre-commit.
  - A CI `docker` job that builds both images, starts the stack with a dummy key, and runs the smoke test.
  - The same job also asserts that the backend is not root and that there is no `.env` inside the images.

## Decisions
- **Editable install in the backend image.** The code finds `config/` relative to its source folder. A regular `pip install` moves the code into site-packages and would break that path.
  Changing how config is located would have been a code change outside this phase's scope.
- **`USER 10001`, numeric.** Scanners and Kubernetes' `runAsNonRoot` can verify a numeric id without reading `/etc/passwd` (hadolint DL3066).
- **`proxy_read_timeout 3600s` on `/live`.** nginx closes a proxied connection after 60 s without data by default, and a quiet sea can be silent for longer.
  Verified: a `/live` connection stayed open through 75 s of silence.
- **Only nginx is published.** The backend is reachable only on the compose network.
- **Dev workflow unchanged.** Containers are for running the app; development still uses `uvicorn --reload` and `npm run dev`.
- **nginx master runs as root.** This is standard for the official image. An unprivileged nginx image is a possible hardening step, not done here.

## Verified (in the dev container)
- Both images build.
- `docker compose up` brings both services up healthy, and the smoke test passes.
- `id -u` in the backend container is `10001`.
- `find / -name .env` finds nothing in either image.
- Image sizes: backend about 208 MB, frontend about 94 MB.
- The dev container needs proxy and CA settings to download packages during a build.
  This was handled outside the repository: local base images with the CA added, plus `--network host`. **The Dockerfiles have nothing environment-specific in them.**
  Live AIS data could not be reached from there; with a real `.env` on a normal machine, ships appear.

## What the agent got wrong
| Problem | How it was caught | What changed |
|---|---|---|
| The first backend Dockerfile created the user in a second `RUN` step and used a user name, not a numeric id, in `USER`. | hadolint (DL3059, DL3066). | One `RUN`; `USER 10001`. |
| **The production map was blank.** MapLibre 6's web worker was not copied by `vite build`. nginx's `index.html` fallback then served the page in its place with status 200. Unit tests, `tsc`, the build and the HTTP smoke test all passed. | **The user**, running the stack on their Mac: the map was black, while ships and alerts were present. In the nginx log, the worker response had the same size as `index.html`. | The worker is imported with `?url` and registered with `setWorkerUrl`, so Vite emits it. `/assets/` returns 404 for missing files. |
| After that fix the worker still failed: nginx's MIME table has no `.mjs`, so it was served as `application/octet-stream` and the browser refused to run it. | The new browser check (below), not the HTTP checks. | nginx serves `/assets/*.mjs` as `application/javascript`. |
| The first new guardrail, an asset scan added to the smoke test, **would not have caught the original bug**: the bundle refers to the worker by bare file name. | The agent ran the new check against the old image, and it passed. | A real-browser check (`frontend/e2e/browser-check.mjs`) in CI. It injects fake ships into `/live` and counts ship-coloured pixels. It fails on the old image (0 pixels, 2 errors) and passes on the fixed one. |
| Phase 3 "verified the UI in a real browser", but only on the **dev server**. The production build was never opened in a browser. | As above. | Lesson: verify the artefact that ships, not the dev setup. |
| A claim in a config comment (nginx closes idle WebSockets after 60 s, so the timeout was raised) was written before it was tested. | Agent applied the "check claims" lesson. | Verified with a 75 s idle connection through nginx. |

## How to run
```bash
cp .env.example .env    # set AISSTREAM_API_KEY
docker compose up --build
# open http://localhost:8080
```
Stop with `Ctrl+C`, or `docker compose down` if it was started with `-d`.
