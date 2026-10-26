# LoopSmith

An **evaluation-gated continual harness** for coding agents, inspired by the
Continual Harness in [Prime Agent](https://www.primeintellect.ai/blog/prime-agent).

Prime Agent's `/refine` lets an agent rewrite its own harness state (memories,
skills, project instructions) from its trajectory. LoopSmith takes the same
idea offline and puts a gate in front of it:

```
import traces -> mine evidence-cited proposals -> evaluate -> human approval
      -> versioned promotion (rollback) -> export Markdown for any coding agent
```

Nothing becomes active without passing static gates *and* a human approval
step. Every version is immutable, so any bad refinement can be rolled back
without losing history.

## Quickstart

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q           # 49 tests, no network
powershell -ExecutionPolicy Bypass -File demo.ps1
```

Or step by step:

```powershell
loopsmith init
loopsmith import examples/traces/acme-api-session1.jsonl --project acme-api
loopsmith import examples/traces/acme-api-session2.jsonl --project acme-api
loopsmith mine
loopsmith proposals list
loopsmith proposals show <id>
loopsmith eval <id>
loopsmith approve <id> --yes --force     # --force: no model configured
loopsmith export                          # -> dist/AGENTS.md, MEMORY.md, skills/, pack
```

## What it does today (P0, fully model-free)

- **Trace import** — canonical JSONL plus a lenient OpenAI-messages-style
  JSONL adapter. Content-hash ids make re-imports no-ops; raw events are
  preserved for provenance.
- **Deterministic miners** — four evidence-cited patterns:
  `command_retry_loop` (flaky command), `user_correction` (preferred
  command), `fix_then_verify` (fail -> edit -> pass cycles), and
  `command_frequency` (the only command that succeeds). Findings merge by
  `(kind, name)` so corroborating signals strengthen one proposal instead of
  duplicating it.
- **Proposals** — the smallest CRUD edit (`create`/`update`) with a
  rationale and citations into trace events. Re-mining is idempotent; new
  evidence after promotion produces an `update` proposal against the active
  version.
- **Evaluation gate** — static checks (body, slug, evidence grounding,
  target freshness, no-op detection) always run. Behavioral A/B is the P1
  hook: without a configured model the verdict is `not_run` and promotion
  requires an explicit `--force`, recorded in the audit log.
- **Approval + versioning** — one active version per entry (enforced by a
  partial unique index), promotion is transactional, rollback is a pointer
  move, and every transition lands in the audit log.
- **Export** — `AGENTS.md` in a managed block that round-trips around
  human-written content, `memory/MEMORY.md`, `skills/<slug>/SKILL.md` with
  frontmatter, and a single `loopsmith-pack.md`. Every section carries its
  version stamp.

## Commands

| Command | Purpose |
|---|---|
| `loopsmith init` | create the SQLite DB (`.loopsmith/loopsmith.db`) |
| `loopsmith import <file> [--project P] [--format auto\|loopsmith\|generic]` | ingest a trace |
| `loopsmith traces list\|show <id>` | inspect imported traces |
| `loopsmith mine [--project P]` | mine proposals |
| `loopsmith proposals list\|show\|diff\|reject` | review evidence and diffs |
| `loopsmith eval <id>` | static gates (+ behavioral A/B once P1 lands) |
| `loopsmith approve <id> [--yes] [--force]` | the human gate |
| `loopsmith history <kind> <name>` | version timeline |
| `loopsmith rollback <kind> <name> [--to N]` | revert to an earlier version |
| `loopsmith export [--out DIR] [--format all\|agents\|memory\|skills\|pack]` | render Markdown |
| `loopsmith status` / `loopsmith doctor` | state and environment checks |

## Evaluation methodology

Two stages, conservative by design:

1. **Static** (always, deterministic): well-formed body, slug validity,
   every evidence ref resolves to a real trace event, target version is
   current (stale proposals are refused), and the body actually differs from
   the active one.
2. **Behavioral A/B** (P1, needs an OpenAI-compatible endpoint): baseline
   harness pack vs candidate pack on a repeatable scenario benchmark.
   Verdict rules: `reject` on any regression or static failure; `promote`
   only with an aggregate gain and zero per-scenario regressions;
   `inconclusive` ties go to baseline.

## Model configuration (optional, P1)

Any OpenAI-compatible `/chat/completions` endpoint works — OpenRouter,
vLLM, LM Studio, or ollama's compat layer. LoopSmith never assumes a
vendor-internal model API.

```powershell
$env:LOOPSMITH_LLM_BASE_URL = "https://openrouter.ai/api/v1"
$env:LOOPSMITH_LLM_API_KEY  = "<key>"
$env:LOOPSMITH_LLM_MODEL    = "cohere/north-mini-code:free"
```

Recommended free coding model (checked Oct 2026): `cohere/north-mini-code:free`
(agentic/terminal coding). Fallbacks: `nvidia/nemotron-3-super-120b-a12b:free`,
`thinkingmachines/inkling-small:free`. The free tier is roughly 50 requests/day
without $10 lifetime credits, so the P1 benchmark defaults to small packs with
N=1 runs and cached arm results.

## Honest scope notes

- The demo traces and the (P1) benchmark scenarios are co-designed so the
  mined refinements have measurable effect. That is demonstration
  methodology, not a general capability claim.
- LoopSmith is batch/offline: it refines from imported traces, it does not
  hook into a live session.
- Approval is mandatory; there is no auto-promotion path.

## Layout

```
src/loopsmith/
  core/      models, SQLite store, versioning (promote/rollback/pack)
  traces/    canonical schema, importers, typed query helpers
  mining/    deterministic miners + merge logic
  eval/      static gates (+ P1 A/B runner hook)
  export/    Markdown renderers
  cli/       Typer commands
examples/traces/   3 demo sessions (acme-api)
tests/             49 tests: store, importers, miners, gates, versioning, render, CLI e2e
demo.ps1           full pipeline walkthrough
```

## Roadmap

- **P1 (headline):** mini agent loop + scenario pack, A/B runner with
  hashes/transcripts/caching, LLM-assisted miner using the same Proposal
  schema.
- **P2:** `claude-code` JSONL adapter, `benchmark smoke`, richer tables,
  eval result tables in the CLI.