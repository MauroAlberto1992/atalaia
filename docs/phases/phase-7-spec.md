# Phase 7 spec — AI workflow and guardrails

Approved before implementation.

## Goal
Make the way the project is built with AI agents visible and verifiable.

## Scope
1. **Guardrails** that run before every commit and in CI:
   - ruff, mypy (strict) and pytest;
   - eslint, tsc and vitest;
   - gitleaks.

   Fix whatever they find, and record it.
2. **Explicit specs.** Specs for phases 0–6 are reconstructed and marked as such. From now on, each phase starts with a spec.
3. **"What the agent got wrong"** in every phase summary, with the problem, how it was caught and what changed.
4. **`docs/ai-workflow.md`** with an honest conclusion for v1.
5. **`CLAUDE.md`:** the new rules and a "Lessons learned" section. **README:** a "Built with AI agents" section.

## Out of scope
New product features.

## Acceptance
- `pre-commit run --all-files` passes, and CI passes.
- A fake API key is blocked by the hook.
