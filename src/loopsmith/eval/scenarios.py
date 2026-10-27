"""Scenario packs: a task prompt + fixture workspace + hidden checker.

Directory convention:
    benchmarks/<pack>/scenarios/<id>/
        task.md            # shown to the agent
        workspace/         # copied into a sandbox for each run
        checker/*.py       # hidden pytest files, graded OUTSIDE the sandbox
        scenario.toml      # optional: max_turns

The pack hash covers every file, so cached results are only reused when
the benchmark itself is unchanged.
"""

import hashlib
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MAX_TURNS = 8


class PackError(ValueError):
    pass


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    task: str
    workspace: Path
    checker: Path
    max_turns: int = DEFAULT_MAX_TURNS


@dataclass(frozen=True)
class Pack:
    id: str
    root: Path
    hash: str
    scenarios: tuple[Scenario, ...]


def _title(task: str, fallback: str) -> str:
    for line in task.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def _hash_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def load_pack(root: Path | str) -> Pack:
    root = Path(root)
    scenarios_dir = root / "scenarios"
    if not scenarios_dir.is_dir():
        raise PackError(f"no scenarios/ directory under {root}")
    scenarios: list[Scenario] = []
    for directory in sorted(p for p in scenarios_dir.iterdir() if p.is_dir()):
        task_path = directory / "task.md"
        workspace = directory / "workspace"
        checker = directory / "checker"
        if not (task_path.is_file() and workspace.is_dir() and checker.is_dir()):
            raise PackError(
                f"scenario '{directory.name}' needs task.md, workspace/ and checker/")
        max_turns = DEFAULT_MAX_TURNS
        meta = directory / "scenario.toml"
        if meta.is_file():
            data = tomllib.loads(meta.read_text(encoding="utf-8"))
            max_turns = int(data.get("max_turns", max_turns))
        task = task_path.read_text(encoding="utf-8").strip()
        scenarios.append(Scenario(
            id=directory.name, title=_title(task, directory.name), task=task,
            workspace=workspace, checker=checker, max_turns=max_turns,
        ))
    if not scenarios:
        raise PackError(f"no scenarios found under {scenarios_dir}")
    return Pack(id=root.name, root=root, hash=_hash_tree(root), scenarios=tuple(scenarios))


def resolve_pack_root(explicit: str | None = None) -> Path:
    """Find the benchmark pack: explicit arg > env > repo > cwd."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env = os.environ.get("LOOPSMITH_BENCHMARKS")
    if env:
        candidates.append(Path(env))
    candidates.append(Path(__file__).resolve().parents[3] / "benchmarks" / "default")
    candidates.append(Path("benchmarks") / "default")
    for candidate in candidates:
        if (candidate / "scenarios").is_dir():
            return candidate
    raise PackError("no benchmark pack found (set LOOPSMITH_BENCHMARKS or --benchmark)")