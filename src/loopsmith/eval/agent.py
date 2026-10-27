"""Bounded mini coding agent used by the A/B benchmark.

Protocol: the model replies with exactly one JSON object per turn:
    {"tool": "<name>", "args": {...}}
Tools are restricted to a sandbox copy of the scenario workspace, paths
cannot escape it, and commands come from a fixed allowlist. Hidden
checkers live outside this sandbox (see runner.grade).
"""

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from loopsmith.eval.llm import extract_json

ALLOWED_COMMANDS = ("python -m pytest -q", "python runtests.py")
DEFAULT_MAX_TURNS = 8
OBSERVATION_LIMIT = 3000
FILE_LIMIT = 20000

TOOL_HELP = """Tools (reply with exactly one JSON object, nothing else):
- {"tool": "list_dir", "args": {"path": "."}}
- {"tool": "read_file", "args": {"path": "app/auth.py"}}
- {"tool": "write_file", "args": {"path": "app/auth.py", "content": "..."}}
- {"tool": "run_command", "args": {"command": "python -m pytest -q"}}
- {"tool": "finish", "args": {"summary": "what you changed and why"}}

Allowed commands: python -m pytest -q | python runtests.py
Call finish when the task is complete. If a test run passes, call finish
immediately instead of exploring further."""

SYSTEM_TEMPLATE = """You are a careful coding agent fixing a small repository.
Work only inside the workspace; use relative paths. Make the smallest change
that solves the task.

{tool_help}

{harness}

# Task

{task}"""

REPEAT_NUDGE = (
    "ERROR: you repeated the exact same action. Read the observation you "
    "already have, change your approach, or call finish if the task is done."
)


@dataclass
class AgentRun:
    transcript: list[dict] = field(default_factory=list)
    turns: int = 0
    finished: bool = False
    final_message: str = ""
    tokens_in: int = 0
    tokens_out: int = 0


class SandboxError(RuntimeError):
    pass


def _safe_path(workspace: Path, rel: str) -> Path:
    root = workspace.resolve()
    candidate = (root / rel).resolve()
    if candidate != root and root not in candidate.parents:
        raise SandboxError(f"path escapes the workspace: {rel}")
    return candidate


def _run_command(command: str, workspace: Path) -> str:
    normalized = " ".join(command.split())
    if normalized not in ALLOWED_COMMANDS:
        return (f"ERROR: command not allowed. Allowed: {', '.join(ALLOWED_COMMANDS)}")
    if normalized == "python -m pytest -q":
        argv = [sys.executable, "-m", "pytest", "-q"]
    else:
        argv = [sys.executable, "runtests.py"]
    try:
        proc = subprocess.run(argv, cwd=workspace, capture_output=True,
                              text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return "ERROR: command timed out after 120s"
    output = (proc.stdout + proc.stderr)[-OBSERVATION_LIMIT:]
    return f"exit={proc.returncode}\n{output}"


def _execute(tool: str, args: dict, workspace: Path) -> tuple[str, bool]:
    """Returns (observation, finished)."""
    if tool == "list_dir":
        target = _safe_path(workspace, str(args.get("path", ".")))
        if not target.is_dir():
            return ("ERROR: not a directory", False)
        entries = sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir())
        return ("\n".join(entries) or "(empty)", False)
    if tool == "read_file":
        target = _safe_path(workspace, str(args.get("path", "")))
        if not target.is_file():
            return (f"ERROR: no such file: {args.get('path')}", False)
        text = target.read_text(encoding="utf-8", errors="replace")
        return (text[:FILE_LIMIT], False)
    if tool == "write_file":
        target = _safe_path(workspace, str(args.get("path", "")))
        content = args.get("content")
        if not isinstance(content, str):
            return ("ERROR: content must be a string", False)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return (f"wrote {len(content)} chars to {args.get('path')}", False)
    if tool == "run_command":
        return (_run_command(str(args.get("command", "")), workspace), False)
    if tool == "finish":
        return (str(args.get("summary", "done")), True)
    return (f"ERROR: unknown tool {tool!r}", False)


def run_agent(llm, scenario, harness_md: str, workspace: Path,
              max_turns: int | None = None) -> AgentRun:
    harness = harness_md.strip()
    system = SYSTEM_TEMPLATE.format(
        tool_help=TOOL_HELP,
        harness=("# Harness guidance\n\n" + harness) if harness else "",
        task=scenario.task,
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "Begin. Reply with one JSON tool call."},
    ]
    run = AgentRun()
    limit = max_turns or scenario.max_turns or DEFAULT_MAX_TURNS
    previous_signature: str | None = None
    repeats = 0
    for turn in range(1, limit + 1):
        result = llm.chat(messages, temperature=0.0, max_tokens=1200)
        run.turns = turn
        usage = result.usage or {}
        run.tokens_in += int(usage.get("prompt_tokens", 0))
        run.tokens_out += int(usage.get("completion_tokens", 0))
        action = extract_json(result.text)
        tool = str(action.get("tool", "")).strip()
        args = action.get("args") or {}
        signature = f"{tool}:{json.dumps(args, sort_keys=True)}"
        repeats = repeats + 1 if signature == previous_signature else 0
        previous_signature = signature
        if repeats >= 2:
            observation, finished = (REPEAT_NUDGE, False)
        elif not tool or not isinstance(args, dict):
            observation, finished = (
                "ERROR: reply must be one JSON object with 'tool' and 'args'", False)
        else:
            try:
                observation, finished = _execute(tool, args, workspace)
            except SandboxError as exc:
                observation, finished = (f"ERROR: {exc}", False)
        run.transcript.append({
            "turn": turn,
            "assistant": (result.text or "")[:2000],
            "tool": tool or None,
            "args": args if isinstance(args, dict) else None,
            "observation": observation[:OBSERVATION_LIMIT],
        })
        if finished:
            run.finished = True
            run.final_message = observation
            break
        messages.append({"role": "assistant", "content": result.text})
        messages.append({"role": "user", "content": f"OBSERVATION:\n{observation}"})
    return run