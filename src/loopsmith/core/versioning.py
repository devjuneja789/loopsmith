"""Promotion, activation, and rollback -- the safety-critical transitions.

Invariants (enforced transactionally):
- At most one active version per entry (partial unique index backs this up).
- Promotion only from a pending/evaluated proposal whose target is current;
  anything else is refused as stale rather than guessed at.
- Rollback is a pointer move: versions are never modified or deleted, so
  history is always complete and any rollback is itself reversible.
"""

from dataclasses import dataclass

from loopsmith.core.models import Entry, EntryVersion, Proposal
from loopsmith.core.store import Store
from loopsmith.core.util import now_utc, sha256_short

KIND_TITLES = {"instruction": "Project instructions", "memory": "Memories", "skill": "Skills"}
SECTION_ORDER = ("instruction", "memory", "skill")


class VersioningError(RuntimeError):
    pass


@dataclass
class PackItem:
    entry: Entry
    version: EntryVersion


def active_pack(store: Store) -> list[PackItem]:
    items = []
    for entry in store.list_entries():
        version = store.active_version(entry.id)
        if version:
            items.append(PackItem(entry, version))
    return items


def pack_items(store: Store, extra: Proposal | None = None) -> list[PackItem]:
    """Active items, with `extra` applied (the candidate view)."""
    items = {item.entry.kind + "/" + item.entry.name: item for item in active_pack(store)}
    if extra is not None:
        key = extra.kind + "/" + extra.name
        if extra.op == "update" and key in items:
            bumped = EntryVersion.model_validate(
                {**items[key].version.model_dump(),
                 "body_md": extra.body_md, "rationale": extra.rationale,
                 "n": (extra.target_n or items[key].version.n) + 1}
            )
            items[key] = PackItem(items[key].entry, bumped)
        elif extra.op == "create" and key not in items:
            placeholder = Entry(
                id="pending", kind=extra.kind, name=extra.name,
                description=None, created_at=now_utc(),
            )
            items[key] = PackItem(placeholder, EntryVersion(
                id="pending", entry_id="pending", n=1, body_md=extra.body_md,
                rationale=extra.rationale, status="candidate", created_at=now_utc(),
            ))
    return sorted(items.values(), key=lambda i: (SECTION_ORDER.index(i.entry.kind), i.entry.name))


def pack_markdown(store: Store, extra: Proposal | None = None) -> str:
    """Render the harness pack (baseline, or candidate with `extra` applied)."""
    lines: list[str] = ["# LoopSmith harness pack", ""]
    for kind in SECTION_ORDER:
        group = [i for i in pack_items(store, extra=extra) if i.entry.kind == kind]
        if not group:
            continue
        title = KIND_TITLES[kind] if kind in KIND_TITLES else kind.title() + "s"
        lines += [f"## {title}", ""]
        for item in group:
            lines += [
                f"### {item.entry.name}",
                "",
                f"<!-- loopsmith: entry={item.entry.name} kind={item.entry.kind} "
                f"version={item.version.n} -->",
                "",
                item.version.body_md.strip(),
                "",
            ]
    return "\n".join(lines).rstrip() + "\n"


def pack_hash(markdown: str) -> str:
    return sha256_short(markdown)


def _description_from(proposal: Proposal) -> str | None:
    for line in proposal.body_md.splitlines():
        if line.startswith("# "):
            return line[2:].strip().replace("`", "")[:100]
    return None


def promote(store: Store, proposal: Proposal, forced: bool = False) -> EntryVersion:
    """Approve a proposal into the next active version, atomically."""
    with store.tx():
        if proposal.status not in ("pending", "evaluated"):
            raise VersioningError(
                f"proposal is {proposal.status}; only pending/evaluated proposals can promote")
        entry = store.get_entry(proposal.kind, proposal.name)
        if proposal.op == "create":
            if entry is not None:
                raise VersioningError(
                    f"stale: {proposal.kind}/{proposal.name} already exists "
                    "(re-mine to propose an update)")
            entry = store.create_entry(
                proposal.kind, proposal.name, _description_from(proposal))
        else:
            if entry is None:
                raise VersioningError(
                    f"stale: {proposal.kind}/{proposal.name} no longer exists")
            active = store.active_version(entry.id)
            if active is None or active.n != proposal.target_n:
                current = active.n if active else 0
                raise VersioningError(
                    f"stale: proposal targets v{proposal.target_n} but active is v{current}")
            if active.body_md.strip() == proposal.body_md.strip():
                raise VersioningError("no-op: identical to the active body")
            store.set_version_status(active.id, "superseded")
        version = store.add_version(entry.id, proposal.body_md, proposal.rationale, "active")
        store.set_proposal_status(proposal.id, "approved")
        store.log("approved", {
            "proposal_id": proposal.id, "kind": proposal.kind, "name": proposal.name,
            "version": version.n, "forced": forced, "origin": proposal.origin,
            "evidence_count": len(proposal.evidence),
        })
    return version


def rollback(store: Store, kind: str, name: str, to_n: int | None = None) -> EntryVersion:
    """Re-point the active version. Never destructive; fully audited."""
    with store.tx():
        entry = store.get_entry(kind, name)
        if entry is None:
            raise VersioningError(f"no entry for {kind}/{name}")
        versions = store.versions(entry.id)
        active = store.active_version(entry.id)
        if active is None:
            raise VersioningError(f"{kind}/{name} has no active version")
        if to_n is None:
            earlier = [v for v in versions if v.n < active.n]
            if not earlier:
                raise VersioningError(
                    f"{kind}/{name} is at v{active.n} with no earlier version to roll back to")
            target = earlier[-1]
        else:
            target = next((v for v in versions if v.n == to_n), None)
            if target is None:
                raise VersioningError(f"{kind}/{name} has no version v{to_n}")
            if target.id == active.id:
                raise VersioningError(f"v{to_n} is already active")
        store.set_version_status(active.id, "reverted")
        store.set_version_status(target.id, "active")
        store.log("rolled_back", {
            "kind": kind, "name": name, "from_version": active.n, "to_version": target.n,
        })
    return target
