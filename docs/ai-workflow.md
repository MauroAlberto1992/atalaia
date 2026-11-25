# How this project is built with AI agents

Almost all of the code in this repository was written by an AI coding agent
(Claude Code). The developer did not write the implementation: they decided
what to build, approved each plan, reviewed the result, ran it against real
data, and asked for changes. This document describes that workflow, the
guardrails around it, and an honest look at where it worked and where it didn't.

## The loop
```
 context (CLAUDE.md)
        │
        ▼
 spec for the phase ──► developer approves ──► agent implements + tests
        ▲                                              │
        │                                              ▼
 lessons go back into CLAUDE.md ◄── review, live run ◄── guardrails (pre-commit, CI)
```

1. **Context: `CLAUDE.md`.** Loaded by the agent at the start of every session:
   - the project's purpose and v1 scope;
   - the stack and the architecture;
   - domain gotchas (aisstream quirks, lat/lon order);
   - working rules;
   - lessons learned.

   It is the single most important file. Rules written there apply to every future session without repeating them.
2. **Spec per phase: `docs/phases/phase-N-spec.md`.**
   - The goal, scope, what is out of scope, and acceptance criteria.
   - The agent proposes it, the developer approves it, and only then is code written.
   - Small phases keep each review readable.
3. **Implementation.** The agent writes the code and the tests, runs them, and for UI work checks the page in a headless browser.
4. **Guardrails** (below). They run before every commit and again in CI.
5. **Review and live run.**
   - The developer reads the diff and runs the service on their machine against the real AIS feed.
   - Several bugs were only visible there (see below).
6. **Phase summary: `docs/phases/phase-N.md`.**
   - What was done, the decisions and why, how to run it.
   - A **"What the agent got wrong"** section.
   - Each lesson also goes into `CLAUDE.md`, which closes the loop.

## Who does what
| Agent | Developer |
|---|---|
| Proposes plans and specs | Sets goals and priorities, approves or changes plans |
| Writes code, tests and docs | Decides scope; rejects or redirects |
| Runs tests, linters, type checks, browser checks | Reviews diffs; asks "why?" on anything non-obvious |
| Flags deviations from the spec | Runs it on real hardware and real data |
| Records its own mistakes | Judges domain correctness (what an operator needs, what looks official) |

## Guardrails
Every commit runs these checks (`.pre-commit-config.yaml`). CI runs the same
checks on every push (`.github/workflows/ci.yml`), so `--no-verify` cannot
bypass them.

| Check | Catches |
|---|---|
| `ruff` (lint + format) | Unused code, likely bugs (bugbear), asyncio pitfalls, inconsistent style |
| `mypy --strict` | Untyped or `Any`-typed code paths, wrong return types |
| `pytest` (81 tests) | Regressions in parsing, state, history, alerts, API |
| `eslint` (strict, type-aware + React hooks) | Floating promises, unsafe `any`, impure renders, hook misuse |
| `tsc` with `noUncheckedIndexedAccess` | Lookups that can be `undefined` at runtime |
| `vitest` | Regressions in the store reducers |
| `gitleaks` | API keys or tokens about to be committed (tested: it blocks a fake key) |
| Browser check of the production images | A map that builds and serves but draws nothing (it caught two real bugs) |
| `hadolint` + CI smoke test | Dockerfile mistakes; a stack that builds but doesn't actually serve; root user; `.env` inside images |

**What adding them found** in code that already passed all tests (phase 7.1):
- zone bounding boxes were recomputed on every check, despite the docs saying "precomputed";
- service state lived on an untyped `app.state`;
- dictionary lookups could return `undefined` without the type system knowing;
- promises were left floating;
- `Date.now()` ran on every render;
- a TypeScript version that the linter did not support.

None were caught by tests. That is the point of layering checks.

## Where the agent helped most
- **Speed on well-understood work:**
  - project setup;
  - FastAPI endpoints;
  - Pydantic models;
  - React components;
  - the WebSocket plumbing.

  Each phase took minutes to implement and most of the time went into review.
- **Tests for pure logic.** History filters, the alert rules and the backoff sequence all came with edge-case tests (concave polygons, eviction, out-of-order reports) written alongside the code.
- **Explaining its own decisions.** Every phase summary lists the decisions and why they were made. That made review faster and is the basis of this document.
- **Self-checks it was told to do.** Browser screenshots caught a bug that every test and the build missed (the map drew no ships).

## Where it needed the most supervision
- **The real world.** Its assumptions about the outside world were wrong, and the code still looked right:
  - the aisstream handshake took longer than the library default;
  - the first frame had a shape the docs didn't show;
  - it never checked the developer's Python and Node versions;
  - a bundler broke a library's web worker.

  These only failed on a real run.
- **Domain judgement.** It drew a protected area from memory, and it was wrong. It named an invented zone so that it looked like a real military area. A person looking at the map caught both.
- **Scope.** It added endpoints and fields beyond the approved plan when they seemed useful. It did flag them, but each one needed a decision.
- **"Latest" by default.** It picked the newest major versions without checking that the surrounding tooling supported them.
- **Claims versus code.** Documentation said one thing (a precomputed bounding box) and the code did another. Only a review driven by the type checker found it.

## Developer's view
> _To be written by the developer: where these tools work well, where they fail,
> and what you would change in this workflow for a team._

## Ideas: guardrails for a team
- **Spec template.** A shared `phase-N-spec.md` format (goal, scope, out of scope, acceptance), required before any agent-written code.
- **Review checklist for AI-generated code:**
  - real-world assumptions: versions, timeouts, data formats;
  - deviations from the spec;
  - test data plausibility;
  - claims in the docs versus the code.
- **Shared lessons file.** Team-wide "lessons learned" that every agent session loads, so a mistake caught once is not repeated by anyone.
- **Ownership of guardrails.** The checks live in the repository and in CI. They are not left to each developer's local setup.
