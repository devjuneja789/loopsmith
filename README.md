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
step. With an OpenAI-compatible model configured, a candidate must also win a
repeatable baseline-vs-candidate benchmark. Every version is immutable, so any
bad refinement can be rolled back without losing history.

## Quickstart

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q                              # 86 tests, no network
powershell -ExecutionPolicy Bypass -File demo.ps1        # model-free pipeline
powershell -ExecutionPolicy Bypass -File demo-llm.ps1    # model-backed A/B
```

Step by step:

```powershell
loopsmith init
loopsmith import examples/traces/acme-api-session1.jsonl --project acme-api
loopsmith import examples/traces/acme-api-session2.jsonl --project acme-api
loopsmith mine
loopsmith proposals list
loopsmith proposals show <id>
loopsmith eval <id>                      # static gates; + A/B if a model is set
loopsmith approve <id> --yes --force     # --force only when verdict is not_run
loopsmith export                          # -> dist/AGENTS.md, MEMORY.md, skills/, pack
```

## What it does

- **Trace import** — canonical JSONL plus a lenient OpenAI-messages-style
  adapter. Content-hash ids make re-imports no-ops; raw events are preserved.
- **Deterministic miners** — four evidence-cited patterns:
  `command_retry_loop` (flaky command), `user_correction` (preferred command),
  `fix_then_verify` (fail -> edit -> pass cycles), `command_frequency` (the
  only command that succeeds). Corroborating signals merge into one proposal.
- **LLM-assisted mining** (`mine --llm`) — the model proposes refinements in
  the same schema; every citation is validated against the DB, and ungrounded
  proposals are dropped.
- **Proposals** — the smallest CRUD edit (`create`/`update`) with a rationale
  and citations into trace events. Re-mining is idempotent; new evidence after
  promotion yields an `update` proposal against the active version.
- **Evaluation gate** — static checks always run (body, slug, evidence
  grounding, target freshness, no-op detection). With a model configured, a
  baseline-vs-candidate A/B run on the scenario pack decides promotion.
- **Approval + versioning** — one active version per entry (partial unique
  index), transactional promotion, rollback as a pointer move, full audit log.
- **Export** — `AGENTS.md` in a managed block that round-trips around
  human-written content, `memory/MEMORY.md`, `skills/<slug>/SKILL.md`, and a
  single `loopsmith-pack.md`; every section carries its version stamp.

## Evaluation methodology

Two stages, conservative by design:

1. **Static** (always, deterministic): well-formed body, slug validity, every
   evidence ref resolves, target version is current (stale proposals refused),
   and the body differs from the active one.
2. **Behavioral A/B** (when a model is configured): the baseline harness pack
   vs the candidate pack (baseline + proposal) run on
   `benchmarks/default/scenarios/`. Each scenario has a task, a fixture
   workspace and hidden `pytest` checkers. The agent works in a sandbox copy
   with five tools (`list_dir`, `read_file`, `write_file`, `run_command`,
   `finish`) and a fixed command allowlist; the graders run outside that
   sandbox so a run can't game its own score.

Verdicts: `reject` on any per-scenario regression or aggregate loss;
`promote` only with an aggregate gain and zero regressions; `inconclusive`
ties go to baseline. Without a model the verdict is `not_run` and approval
requires an explicit, audited `--force`.

Reproducibility: pack contents are hashed, the model name and params are
recorded, and full transcripts land in `.loopsmith/runs/`. Arms are cached by
(benchmark hash, pack hash, model, scenario, arm, repetition), so shared
baselines never re-spend API budget. A durable snapshot of a live model-backed
evaluation run is preserved in `evidence/` for inspection without spending API quota.

Budget note: OpenRouter's free tier allows roughly 50 requests/day without
$10 lifetime credits. The full pack is 3 scenarios × 2 arms × 1 run
(~30-48 requests); `--scenario <id>` restricts the run to one fixture
(~8-16 requests), and arms are cached so repeat evaluations are cheap.
`demo-llm.ps1` defaults to a single scenario for exactly this reason. Expect
`inconclusive` when a small model ignores the harness; raise `--runs` once you
have credits.

## Model configuration (OpenAI-compatible only)

Any endpoint speaking `POST /chat/completions` works: OpenRouter, vLLM,
LM Studio, or ollama's compat layer. LoopSmith never assumes a vendor-internal
model API.

```powershell
$env:LOOPSMITH_LLM_BASE_URL = "https://openrouter.ai/api/v1"
$env:LOOPSMITH_LLM_API_KEY  = "<key>"
$env:LOOPSMITH_LLM_MODEL    = "cohere/north-mini-code:free"
```

Or put the same three `KEY=VALUE` lines in a `.env` file next to `pyproject.toml`:
LoopSmith loads it automatically (without overriding real environment variables).
Set `LOOPSMITH_SKIP_DOTENV=1` to ignore it — `demo.ps1` does this to stay
model-free.

Recommended free coding model (checked Oct 2026): `cohere/north-mini-code:free`
(agentic/terminal coding). Fallbacks: `nvidia/nemotron-3-super-120b-a12b:free`,
`thinkingmachines/inkling-small:free`. Poolside Laguna is skipped: its free
endpoint expires 2026-10-31.

## Commands

| Command | Purpose |
|---|---|
| `loopsmith init` | create the SQLite DB (`.loopsmith/loopsmith.db`) |
| `loopsmith import <file> [--project P] [--format auto\|loopsmith\|generic]` | ingest a trace |
| `loopsmith traces list\|show <id>` | inspect imported traces |
| `loopsmith mine [--project P] [--llm]` | mine proposals (heuristics, optional model) |
| `loopsmith proposals list\|show\|diff\|reject` | review evidence and diffs |
| `loopsmith eval <id> [--runs N] [--scenario ID ...] [--benchmark DIR]` | static gates + A/B when a model is set |
| `loopsmith runs [run-id]` | list eval runs, or inspect one run's results and transcripts |
| `loopsmith benchmark list` | list scenarios and the pack hash |
| `loopsmith benchmark smoke` | prove fixtures start unsolved (checker sanity) |
| `loopsmith approve <id> [--yes] [--force]` | the human gate |
| `loopsmith history <kind> <name>` | version timeline |
| `loopsmith rollback <kind> <name> [--to N]` | revert to an earlier version |
| `loopsmith export [--out DIR] [--format all\|agents\|memory\|skills\|pack]` | render Markdown |
| `loopsmith status` / `loopsmith doctor` | state and environment checks |

## Honest scope notes

- The demo traces and benchmark scenarios are co-designed so the mined
  refinements can matter. That is demonstration methodology, not a general
  capability claim; `inconclusive` is a legitimate outcome.
- LoopSmith is batch/offline: it refines from imported traces, it does not hook
  into a live session.
- Approval is mandatory; there is no auto-promotion path.

## Layout

```
src/loopsmith/
  core/      models, SQLite store, versioning (promote/rollback/pack)
  traces/    canonical schema, importers, typed query helpers
  mining/    deterministic miners + merge logic
  eval/      static gates, LLM client, mini agent, scenario pack, A/B runner, LLM miner
  export/    Markdown renderers
  cli/       Typer commands
evidence/                       durable live evaluation snapshot and transcripts
benchmarks/default/scenarios/   3 fixtures (task + workspace + hidden checker)
examples/traces/                3 demo sessions (acme-api)
tests/                          86 tests: unit, runner/agent, CLI e2e (no network)
demo.ps1 / demo-llm.ps1         model-free and model-backed walkthroughs
```

## Roadmap

- **Expanded Traces:** `claude-code` JSONL adapter and additional agent trace formats.
- **CLI Polish:** Richer terminal tables and interactive evaluation run history.
- **Advanced Tool Calling:** Optional OpenAI-style native tool calling for frontier models.