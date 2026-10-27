# Live A/B run evidence (2026-10-26)

First real model-backed evaluation, kept as a self-contained snapshot.

| Field | Value |
|---|---|
| Run id | `r05b3ff757652` |
| Model | `cohere/north-mini-code:free` via OpenRouter |
| Proposal | `instruction/use-python-runtests-py` (mined from `examples/traces/`) |
| Benchmark | one scenario: `acme-auth-fix` (pack provided ad hoc to keep quota use low) |
| Repetitions | 1 per arm |
| Verdict | `inconclusive` -- both arms solved the task (100% vs 100%), ties go to baseline |
| Tokens | baseline 5,281 / candidate 6,043 |
| Turns | 8 / 8 |
| API cost | $0.00 (free model) |
| Requests | 16 (two arms x 8 turns) |

Both arms explored the repo (`list_dir` -> README/runtests.py), read the visible
tests and `app/auth.py`, ran the project test entrypoint, fixed the password
comparison, and re-ran green. The mined instruction was not decisive here, so
the gate refused to promote -- the intended behaviour for a tie.

## Inspect it

```powershell
$env:LOOPSMITH_DB = "evidence/live-ab-2026-10-26/loopsmith.db"
loopsmith runs
loopsmith runs r05b3ff757652
```

Contents:

- `loopsmith.db` -- traces, proposals, and the eval run with per-arm results
- `runs/*.json` -- full agent transcripts and grader output for both arms

Note: a later model-free `demo.ps1` run reset the repo `.loopsmith/` database,
so this snapshot is the durable copy of the live evaluation. Re-running
`demo-llm.ps1` regenerates a fresh in-repo run (costs ~8-16 requests).
