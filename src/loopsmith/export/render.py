"""Markdown export of the approved harness pack.

Destinations:
- AGENTS.md  : project instructions in a managed block (round-trips
              without clobbering human-written content)
- MEMORY.md  : one section per active memory entry
- skills/<slug>/SKILL.md : agent-skill convention (frontmatter + body)
- loopsmith-pack.md : everything, for any agent's context

Every section is stamped with its entry kind and version for provenance.
"""

from pathlib import Path

from loopsmith.core import versioning
from loopsmith.core.models import Entry, EntryVersion
from loopsmith.core.store import Store

MARK_BEGIN = "<!-- loopsmith:begin -->"
MARK_END = "<!-- loopsmith:end -->"


def _section(entry: Entry, version: EntryVersion) -> str:
    return (
        f"## {entry.name}\n\n"
        f"<!-- loopsmith: entry={entry.name} kind={entry.kind} version={version.n} -->\n\n"
        f"{version.body_md.strip()}\n"
    )


def _by_kind(store: Store, kind: str) -> list[tuple[Entry, EntryVersion]]:
    out = []
    for item in versioning.active_pack(store):
        if item.entry.kind == kind:
            out.append((item.entry, item.version))
    return out


def instructions_block(store: Store) -> str:
    items = _by_kind(store, "instruction")
    if not items:
        return ""
    return "# LoopSmith project instructions\n\n" + "".join(_section(e, v) for e, v in items)


def export_agents_md(store: Store, path: Path) -> Path | None:
    """Write/patch the managed block in an AGENTS.md file."""
    block = instructions_block(store)
    if not block:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if MARK_BEGIN in text and MARK_END in text:
            before, rest = text.split(MARK_BEGIN, 1)
            _, after = rest.split(MARK_END, 1)
            text = f"{before}{MARK_BEGIN}\n{block}\n{MARK_END}{after}"
        else:
            text = text.rstrip() + f"\n\n{MARK_BEGIN}\n{block}\n{MARK_END}\n"
    else:
        text = (
            "# AGENTS.md\n\nProject instructions for coding agents.\n"
            f"The loopsmith block below is managed by `loopsmith export`.\n\n"
            f"{MARK_BEGIN}\n{block}\n{MARK_END}\n"
        )
    path.write_text(text, encoding="utf-8")
    return path


def export_memory_md(store: Store, path: Path) -> Path | None:
    items = _by_kind(store, "memory")
    if not items:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "# Project memories\n\n" + "".join(_section(e, v) for e, v in items)
    path.write_text(text, encoding="utf-8")
    return path


def export_skills(store: Store, out_dir: Path) -> list[Path]:
    paths = []
    for entry, version in _by_kind(store, "skill"):
        skill_dir = out_dir / "skills" / entry.name
        skill_dir.mkdir(parents=True, exist_ok=True)
        body = (
            "---\n"
            f"name: {entry.name}\n"
            f"description: {(entry.description or entry.name)[:100]}\n"
            f"version: {version.n}\n"
            "---\n\n"
            f"{version.body_md.strip()}\n"
        )
        path = skill_dir / "SKILL.md"
        path.write_text(body, encoding="utf-8")
        paths.append(path)
    return paths


def export_pack_md(store: Store, path: Path) -> Path | None:
    items = versioning.active_pack(store)
    if not items:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(versioning.pack_markdown(store), encoding="utf-8")
    return path


def export_all(store: Store, out_dir: Path, which: str = "all") -> list[Path]:
    """Export selected formats; returns the files written."""
    which_l = which.lower()
    written: list[Path] = []

    def want(fmt: str) -> bool:
        return which_l in ("all", fmt)

    if want("agents"):
        if p := export_agents_md(store, out_dir / "AGENTS.md"):
            written.append(p)
    if want("memory"):
        if p := export_memory_md(store, out_dir / "memory" / "MEMORY.md"):
            written.append(p)
    if want("skills"):
        written.extend(export_skills(store, out_dir))
    if want("pack"):
        if p := export_pack_md(store, out_dir / "loopsmith-pack.md"):
            written.append(p)
    if written:
        store.log("exported", {"files": [str(p) for p in written]})
    return written
