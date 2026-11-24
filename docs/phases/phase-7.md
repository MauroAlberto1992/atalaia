# Phase 7 — AI workflow and guardrails

## Done
- **Guardrails.**
  - `.pre-commit-config.yaml`: the generic hooks, gitleaks, then ruff, mypy (strict) and pytest for the backend, and eslint, tsc and vitest for the frontend.
  - `.github/workflows/ci.yml`: the same checks plus a frontend build and a gitleaks scan of the full history.
  - The dev tools are pinned in `pyproject.toml` (dev extras) and `package.json`.
- **Fixes the new checks forced:**
  - service state moved into a typed `Runtime` object;
  - zone bounding boxes are now computed once;
  - `noUncheckedIndexedAccess` is on;
  - promises are no longer left floating;
  - lazy `useState`;
  - no non-null assertions;
  - errors are rejected as `Error` objects;
  - TypeScript 7 replaced by 6.0.
- **Specs** `phase-0-spec.md` … `phase-6-spec.md` (reconstructed) and `phase-7-spec.md`.
- **"What the agent got wrong"** added to `phase-0.md` … `phase-6.md`.
- **`docs/ai-workflow.md`**; `CLAUDE.md` rules and lessons; README section.

## Decisions
- **Local hooks use `language: system`.** They run with the developer's own venv and node_modules, so the versions match what the developer runs by hand. CI installs from the same manifests.
- **The rules are strict and few are turned off.** Two exceptions, each with a comment:
  - `no-confusing-void-expression`: style only;
  - `_`-prefixed unused variables: intentional destructuring.
- **No runtime schema validation for `/live` messages.** The source is our own backend; the TypeScript types are the contract. This is noted in the code.
- **The developer's opinion is left blank in `ai-workflow.md`.** It has to be the developer's own.

## What the agent got wrong
| Problem | How it was caught | What changed |
|---|---|---|
| Installed TypeScript 7, which typescript-eslint doesn't support yet. | `npm install` peer-dependency error when adding ESLint. | Downgraded to 6.0; the "don't default to latest" lesson is in `CLAUDE.md`. |
| Phase 3 added `engines` to `package.json`, but npm only warns on it. The user's Node 20.11 broke vitest with a cryptic `styleText` error, and the same thing had already happened once before with `npm run dev`. | The user's first `pre-commit run`. | `frontend/.npmrc` with `engine-strict=true`: `npm install` now fails with a clear `EBADENGINE` (tested). `frontend/.nvmrc` pins Node 22 for `nvm use`. |
| `2**n` with an `int` is typed `Any`, so a "float" function was returning `Any`. | mypy strict. | Use a float base. |

## How to run
```bash
pip install -e "backend[dev]"   # with the backend venv active
pre-commit install              # once per clone
pre-commit run --all-files      # the same checks CI runs
```
