from conftest import promote_forced
from loopsmith.export import render
from loopsmith.mining import heuristics


def _approved_store(populated_store):
    for proposal in heuristics.mine(populated_store):
        promote_forced(populated_store, proposal)
    return populated_store


def test_export_all_writes_four_files(populated_store, tmp_path):
    store = _approved_store(populated_store)
    out = tmp_path / "dist"
    written = render.export_all(store, out)
    names = sorted(p.relative_to(out).as_posix() for p in written)
    assert names == [
        "AGENTS.md",
        "loopsmith-pack.md",
        "memory/MEMORY.md",
        "skills/verify-after-edit/SKILL.md",
    ]


def test_agents_md_contains_managed_block(populated_store, tmp_path):
    store = _approved_store(populated_store)
    path = render.export_agents_md(store, tmp_path / "AGENTS.md")
    text = path.read_text(encoding="utf-8")
    assert render.MARK_BEGIN in text and render.MARK_END in text
    assert "use-make-test" in text
    assert "version=1" in text


def test_agents_md_patches_existing_block(populated_store, tmp_path):
    store = _approved_store(populated_store)
    path = tmp_path / "AGENTS.md"
    path.write_text(
        "# AGENTS.md\n\nHuman notes stay.\n\n"
        f"{render.MARK_BEGIN}\nstale content\n{render.MARK_END}\n\nfooter\n",
        encoding="utf-8",
    )
    render.export_agents_md(store, path)
    text = path.read_text(encoding="utf-8")
    assert "Human notes stay." in text
    assert "footer" in text
    assert "stale content" not in text
    assert "use-make-test" in text


def test_agents_md_appends_when_markers_missing(populated_store, tmp_path):
    store = _approved_store(populated_store)
    path = tmp_path / "AGENTS.md"
    path.write_text("# AGENTS.md\n\nExisting.\n", encoding="utf-8")
    render.export_agents_md(store, path)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# AGENTS.md\n\nExisting.")
    assert render.MARK_BEGIN in text


def test_skill_frontmatter(populated_store, tmp_path):
    store = _approved_store(populated_store)
    render.export_skills(store, tmp_path / "dist")
    skill = (tmp_path / "dist" / "skills" / "verify-after-edit" / "SKILL.md")
    text = skill.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "name: verify-after-edit" in text
    assert "version: 1" in text
    assert "Verify after edit" in text


def test_memory_file(populated_store, tmp_path):
    store = _approved_store(populated_store)
    path = render.export_memory_md(store, tmp_path / "memory" / "MEMORY.md")
    text = path.read_text(encoding="utf-8")
    assert "flaky-test-auth-login" in text
    assert "kind=memory" in text


def test_export_nothing_when_no_entries(populated_store, tmp_path):
    assert render.export_all(populated_store, tmp_path / "dist") == []


def test_export_selection(populated_store, tmp_path):
    store = _approved_store(populated_store)
    written = render.export_all(store, tmp_path / "dist", which="skills")
    assert len(written) == 1
    assert written[0].name == "SKILL.md"