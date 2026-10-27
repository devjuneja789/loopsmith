# LoopSmith

**Turn coding-session traces into reusable agent instructions, with evidence and
checks before anything is promoted.** LoopSmith is an offline refinement
workflow inspired by the [Continual Harness in Prime Agent](https://www.primeintellect.ai/blog/prime-agent).

Coding agents can repeat the same mistakes across sessions. LoopSmith imports
past sessions, finds candidate lessons, checks them against evidence, and
exports approved guidance for future sessions:

```
import traces -> mine evidence-cited proposals -> evaluate -> human approval
      -> versioned promotion (rollback) -> export Markdown for any coding agent
```

Nothing becomes active without passing static checks and human approval. When
an OpenAI-compatible model is configured, LoopSmith also compares the current
guidance with the proposed change on a benchmark pack. Approved changes are
versioned and can be rolled back.

## Quickstart

```powershell
python --version                              # Python 3.11 or newer
python -m pip install -e ".[dev]"
python -m pytest -q                              # test suite; no network
powershell -ExecutionPolicy Bypass -File demo.ps1        # model-free pipeline
powershell -ExecutionPolicy Bypass -File demo-llm.ps1    # model-backed A/B
```

The quickest way to see the project is `demo.ps1`: it imports three example
sessions, mines and reviews proposals, demonstrates the approval gate, exports
Markdown instructions, then shows how a later trace creates a versioned update
that can be rolled back. It needs no API key. The script recreates its local
`.loopsmith/` database and `dist/` export directory, so run it from a clean
checkout or after saving anything in those directories. The LLM walkthrough
uses a configured OpenAI-compatible endpoint and makes API requests.

Step by step:

```powershell
loopsmith init
loopsmith import examples/traces/acme-api-session1.jsonl --project acme-api
loopsmith import examples/traces/acme-api-session2.jsonl --project acme-api
loopsmith mine
loopsmith proposals list
loopsmith proposals show <id>
loopsmith eval <id>                      # static gates; + A/B if a model is set
loopsmith approve <id> --yes --force     # --force records an override
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
- **Proposals** — a focused create or update with a rationale
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

## Live evaluation evidence

The saved [live A/B run summary](evidence/live-ab-2026-10-26/SUMMARY.md) records
one model-backed run on `acme-auth-fix`. The baseline and candidate both fixed
the authentication bug and passed the grader (100% each), so LoopSmith returned
`inconclusive` and left the mined instruction unpromoted. The candidate was not
decisive in this task; the result demonstrates the no-promotion-on-a-tie gate,
not a general performance gain.

The run used one repetition per arm and 16 API requests; the recorded cost was
$0.00 on the free model at the time. The summary links to the stored database
and full transcripts for inspection. This is a small, single-scenario snapshot,
not a broad benchmark claim.

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

The model-backed demo runs one scenario to limit API usage; the full pack has
three scenarios, and `--scenario <id>` can select a single fixture. Results are
cached by benchmark, harness pack, model, scenario, arm, and repetition, so
unchanged arms can be reused. Outcomes depend on the configured model; ties are
`inconclusive` and remain unpromoted unless a person explicitly overrides.

## Model configuration (OpenAI-compatible only)

Any endpoint speaking `POST /chat/completions` works: OpenRouter, vLLM,
LM Studio, or ollama's compat layer. LoopSmith never assumes a vendor-internal
model API.

```powershell
$env:LOOPSMITH_LLM_BASE_URL = "<provider-base-url>"
$env:LOOPSMITH_LLM_API_KEY  = "<key>"
$env:LOOPSMITH_LLM_MODEL    = "<model-id>"
```

Or put the same three `KEY=VALUE` lines in a `.env` file next to `pyproject.toml`:
LoopSmith loads it automatically (without overriding real environment variables).
Set `LOOPSMITH_SKIP_DOTENV=1` to ignore it — `demo.ps1` does this to stay
model-free.

Choose a model that can follow tool-use instructions and edit code. Model names,
availability, and pricing vary by provider; consult your endpoint provider for
current options.

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

## For hackathon reviewers

The core demo is reproducible without credentials: run `demo.ps1` to see the
full trace-to-approved-export loop, including a later update and rollback. The
optional `demo-llm.ps1` shows behavioral A/B evaluation on task fixtures. See
[the saved live run](evidence/live-ab-2026-10-26/SUMMARY.md) for an example of
the benchmark and promotion gate in action.

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
tests/                          unit, runner/agent, CLI e2e tests (no network)
demo.ps1 / demo-llm.ps1         model-free and model-backed walkthroughs
```

## Roadmap

- **Expanded Traces:** `claude-code` JSONL adapter and additional agent trace formats.
- **CLI Polish:** Richer terminal tables and interactive evaluation run history.
- **Advanced Tool Calling:** Optional OpenAI-style native tool calling for frontier models.
