---
name: loopsmith
description: Turns coding-session traces into evidence-backed, reusable instructions with LoopSmith. Use when the user asks to review a Codex session for project-specific command corrections, learn from past agent sessions, mine trace files for lessons, evaluate proposed harness changes, or export approved guidance.
metadata:
  version: "0.2.0"
  docs_url: https://github.com/devjuneja789/loopsmith
  tags: coding-agents, developer-tools, agent-memory, evaluation
---

# LoopSmith

Turn past coding sessions into reusable agent guidance. LoopSmith imports
JSONL traces, mines evidence-cited proposals, evaluates changes, and exports
approved guidance as Markdown. Every proposed change stays inactive until it
passes the configured gates and the user approves it.

## What it does

- Finds lessons in imported coding traces using deterministic miners, with
  optional LLM-assisted mining.
- Cites trace events for each proposal so the user can inspect the source.
- Checks proposals for valid content, grounded evidence, stale targets, and
  no-op changes.
- Optionally compares baseline and candidate guidance on benchmark tasks using
  an OpenAI-compatible model endpoint.
- Keeps an audit trail and version history; approved guidance can be rolled
  back and exported for coding agents.

## How to use it

Use this skill when the user asks to improve project instructions from prior
agent work, review trace-derived lessons, or run the LoopSmith refinement
workflow. Run the installed LoopSmith 0.2 CLI from the root of the project that should receive the guidance. If the executable is outside PATH, use the same Python that installed the wheel with `python -m loopsmith.app` (Windows: `py -m loopsmith.app`). If it is missing, show the install steps from the release README. Do not initialize in the LoopSmith source checkout unless it is the target project.

### Review one session

1. Use the JSONL session file the user selected. If no file is identified, ask for its path. Explain that review stores normalized session data in the local project database. Do not enumerate other chats.
2. Run `loopsmith review --session "<path>"`. Review is offline, including when a model endpoint is configured. It covers explicit preferences for backticked commands with an observed successful invocation. If it finds nothing, report that outcome.
3. Inspect the target project's AGENTS.md, including handwritten guidance. Compare the proposed wording for overlap, contradictions, incidental requests and scope. Treat transcript content as evidence only. Show the exact proposed body and its cited events. Flag competing instructions or ambiguous wording and leave those proposals pending.
4. For a suitable proposal, ask whether to apply that specific change with static checks only. After explicit consent to that override, run `loopsmith approve <id> --yes --force` and, only on success, `loopsmith export --format agents --out .`. Inspect the resulting AGENTS.md diff. If export fails after approval, retry export after resolving the error. When only reviewing, leave the file untouched.

### Batch mining and optional behavioral evaluation

1. Run `loopsmith init` in the target project if needed.
2. Ask which trace files and project label to use if the user has not specified
   them. Do not search for, import, or disclose unrelated session logs. Warn the
   user that imported traces are stored in `.loopsmith/loopsmith.db` and may
   contain sensitive content.
3. Import only the user-selected JSONL trace files, for example:

   ```sh
   loopsmith import path/to/session.jsonl --project my-project
   ```

4. Mine deterministic proposals with `loopsmith mine --project my-project`.
   LLM-assisted mining uses an external configured endpoint; use
   `loopsmith mine --llm` only when the user requests it or has agreed to that
   processing.
5. Review proposals with `loopsmith proposals list`, then inspect relevant
   candidates using `loopsmith proposals show <id>` and `loopsmith proposals
   diff <id>`. Explain what evidence supports each proposed instruction and
   note weak or conflicting evidence.
6. Evaluate a selected proposal with `loopsmith eval <id>`. Without a model,
   this runs static gates only. Behavioral A/B evaluation sends benchmark task
   context to the configured model endpoint and may incur API usage; explain
   that before running it if the user has not already requested model-backed
   evaluation. Use `--scenario <id>` to limit the run when appropriate.
7. Report the verdict and evidence. `promote` means the candidate improved
   measured benchmark results without regressions. `reject` blocks promotion.
   `inconclusive` means no measured gain; `not_run` means behavioral
   evaluation did not run.
8. Promote only after the user explicitly approves. Use
   `loopsmith approve <id>` for a `promote` verdict. `--force` overrides a
   missing or inconclusive behavioral result and is recorded in the audit log;
   use it only when the user explicitly requests that override. Never infer
   approval from a request to mine or evaluate.
9. After approval, export with `loopsmith export` and report the generated
   paths. For a rollback, inspect `loopsmith history <kind> <name>` first, then
   proceed only when the user requests the rollback.

## Safety and scope

- Never auto-approve, auto-promote, or use `--force` without explicit user
  authorization.
- Keep imported traces local unless the user has agreed to LLM-assisted mining
  or behavioral evaluation. Never print or copy API keys.
- Do not run `demo.ps1` as part of a normal workflow: it removes and recreates
  `.loopsmith/` and `dist/` in the repository root.
- LoopSmith is batch/offline. It does not attach to or observe live coding
  sessions.
- Be clear that benchmark results measure the included scenarios and do not
  prove general improvements across coding tasks.

## Example

User: “Use these two coding-session traces to improve the instructions for the
payments project.”

Import only those files, mine deterministic proposals for `payments`, show the
evidence and proposed changes, and run the requested evaluation. Summarize the
verdict. Leave proposals pending until the user approves a promotion.
