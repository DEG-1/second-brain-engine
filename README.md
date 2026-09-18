# Second Brain — Multi-Agent Orchestration Engine

A **100% local, terminal-only** "second brain" that orchestrates two AI coding
CLIs — **Claude Code** and **Codex** — as non-interactive subprocesses to
plan, execute, review and merge software work autonomously, with a durable
memory, per-task Git isolation, budget control and a full recovery model.

Pure Python. Single machine. No server, no cloud state.

> **About this repository.** This is a **curated public extract** of a larger
> private codebase. It ships the coherent, self-contained core — the state
> machine, event bus, domain model, configuration system and utilities — with
> their full test suite (see *Explore & extend*). The heavy orchestration
> internals, the CLI adapters, the Textual UI and the security-policy internals
> are intentionally not published here. The sections below describe the full
> system and its roadmap.

---

## What it does

Given an objective, Second Brain drives a full software-delivery cycle:

1. **Inspect** — index the repo (Tree-sitter), build a repository map and
   assemble selective context from a persistent memory vault.
2. **Discuss** — the two coordinators (FABLE / Claude and SOL / Codex) hold a
   bounded, structured negotiation over the approach.
3. **Plan** — the orchestrator consolidates their closing statements into one
   task plan and waits for **human approval**.
4. **Execute** — each coordinator works in its **own Git worktree** (fully
   isolated from `main`), turn by turn, and may spawn small, contract-bound
   **workers** for delimited sub-tasks.
5. **Cross-review** — each coordinator reviews the other's branch; up to two
   correction rounds before pausing for a human decision.
6. **Merge** — sequential, human-approved integration into `main`, with
   conflict-resolution turns and re-testing after each rebase.
7. **Summarize** — dated summaries, handoffs and a checkpoint close the cycle.

Everything streams typed events to a live terminal UI, and every boundary is
checkpointed so the cycle survives a hard restart.

---

## Technical highlights

- **Deterministic orchestration over non-deterministic agents.** The LLMs
  produce structured JSON at turn boundaries; the orchestrator is the single
  source of control-flow truth. Agents never touch `main` or run sensitive
  actions silently.
- **Durable memory as the operational source of truth.** SQLite is the
  authority; all human-readable Markdown/JSON is *generated* from it in one
  direction, with a regenerability contract.
- **Per-task Git isolation.** Coordinators and workers each get their own
  worktree and branch; nothing merges automatically.
- **Three-layer security model.** CLI permission modes → per-CLI flags;
  worktree isolation; and an orchestrator-side command classifier plus a
  protected-paths policy (data-driven, add-only). *(Policy internals are kept
  private.)*
- **Budget control.** Per-phase token budgets with 60/80/90/100 % thresholds,
  automatic compaction of the heaviest session, and a hard human-approval pause
  on overrun.
- **Full recovery model.** Checkpoints at every boundary; on restart the engine
  reconciles orphaned worker processes, verifies worktrees and **reconstructs
  an in-progress cycle** (resuming coordinator sessions or opening fresh ones
  with condensed context) instead of discarding the work.
- **Robust process handling.** asyncio subprocess management with guaranteed
  process-tree teardown, streaming JSON with no data loss, single-writer SQLite
  from concurrent coroutines.
- **Live terminal UI.** A Textual app with per-coordinator panels, a worker
  board, a live conversation log and ten function-key views — plus a REPL
  fallback.

---

## Architecture

```
second_brain/
  core/        orchestrator, state machine, event bus, command parser
  agents/      Claude/Codex adapters, worker lifecycle, prompts, JSON parser
  memory/      SQLite + migrations, vault, retrieval (FTS5), repository map
  vcs/         Git worktrees, diff, sequential merge, destructive-op safety
  processes/   asyncio subprocess runner, stream reader, tree cancellation
  ui/          Textual app: widgets, screens, controller, event relay
  security/    command classifier, protected paths, permission policy
  utils/       paths, timestamps, atomic JSON, logging
```

- **Single event schema** shared by the in-memory bus and the `events` table.
- **Numbered SQL migrations** with a `schema_version` table.
- **Portable mode**: global state lives under a relocatable home directory;
  packaged resources are accessed only through `importlib.resources`.

---

## Project status & roadmap

The core engine is complete and audited through the security and recovery
layers. Delivery is **phased**: each phase is built, adversarially QA'd and
independently audited before merge, with every finding fixed and re-verified.

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Core: orchestrator, state machine, event bus, multi-project registry | ✅ Done |
| 2 | Real Claude / Codex CLI adapters, process runner | ✅ Done |
| 3 | Real coordinator discussion, session continuity | ✅ Done |
| 4 | Memory: indexer, repo map, FTS5 retrieval, compaction | ✅ Done |
| 5 | Git worktrees, diff, sequential merge with approval | ✅ Done |
| 6 | Workers, contracts, token budgets | ✅ Done |
| 7 | Textual terminal UI (panels, F1–F10 views, commands) | ✅ Done |
| 8 | Security model, restart recovery | ✅ Core done |
| 9 | PyInstaller packaging, docs, Windows hardening | ⏳ Pending |

**Known follow-ups (good places to complement):** deeper cycle reconstruction
for the review/correction phases, resuming a blocked worker's session, an audit
trail for sensitive actions, a vault-regenerability test suite, and the
standalone Windows binary.

~780 automated tests across the full project (unit + integration + e2e), strict
`mypy` and `ruff` clean, deterministic fake-CLI tests plus a `--demo` mode that
runs a whole cycle with zero quota usage.

---

## Explore & extend (this extract)

The published subset is a working, tested slice you can run directly:

```bash
python -m venv .venv && . .venv/Scripts/activate   # (Windows) or bin/activate
pip install -e ".[dev]"
pytest -q            # the included tests pass on this subset
```

Good entry points:

- `second_brain/core/state_machine.py` — the deterministic cycle state machine.
- `second_brain/core/event_bus.py` — the typed event bus (single schema).
- `second_brain/memory/models.py` — the whole domain model (Pydantic).
- `second_brain/config.py` — layered, validated configuration.
- `second_brain/agents/base.py` — the coordinator-adapter interface.

Contributions and questions are welcome via issues and pull requests.

---

## Tech stack

Python 3.14 · asyncio · SQLite (aiosqlite) + FTS5 · Tree-sitter · Textual ·
Pydantic · PyYAML · Git worktrees · pytest / mypy / ruff · PyInstaller.

Integrates with **Claude Code** and **Codex** CLIs as the coordinating agents.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
