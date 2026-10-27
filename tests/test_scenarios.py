import shutil
from pathlib import Path

import pytest

from loopsmith.eval.scenarios import PackError, load_pack, resolve_pack_root

DEFAULT_PACK = Path(__file__).resolve().parents[1] / "benchmarks" / "default"


def test_load_default_pack():
    pack = load_pack(DEFAULT_PACK)
    assert pack.id == "default"
    assert {s.id for s in pack.scenarios} == {
        "acme-auth-fix", "acme-ci-red", "acme-flaky-pricing"}
    assert pack.hash
    for scenario in pack.scenarios:
        assert scenario.task.startswith("# ")
        assert scenario.workspace.is_dir()
        assert any(scenario.checker.iterdir())
        assert scenario.max_turns == 8


def test_hash_is_content_stable(tmp_path):
    copy = tmp_path / "default-copy"
    shutil.copytree(DEFAULT_PACK, copy)
    assert load_pack(DEFAULT_PACK).hash == load_pack(copy).hash


def test_hash_changes_with_content(tmp_path):
    copy = tmp_path / "default-copy"
    shutil.copytree(DEFAULT_PACK, copy)
    task = copy / "scenarios" / "acme-auth-fix" / "task.md"
    task.write_text(task.read_text(encoding="utf-8") + "\nExtra words.\n", encoding="utf-8")
    assert load_pack(DEFAULT_PACK).hash != load_pack(copy).hash


def test_missing_scenario_parts_are_rejected(tmp_path):
    (tmp_path / "scenarios" / "broken").mkdir(parents=True)
    with pytest.raises(PackError, match="needs task.md"):
        load_pack(tmp_path)


def test_empty_pack_is_rejected(tmp_path):
    (tmp_path / "scenarios").mkdir()
    with pytest.raises(PackError, match="no scenarios"):
        load_pack(tmp_path)


def test_explicit_root_wins(tmp_path, monkeypatch):
    pack_root = tmp_path / "custom"
    (pack_root / "scenarios").mkdir(parents=True)
    monkeypatch.setenv("LOOPSMITH_BENCHMARKS", str(tmp_path / "missing"))
    assert resolve_pack_root(str(pack_root)) == pack_root


def test_env_root_is_used(tmp_path, monkeypatch):
    pack_root = tmp_path / "from-env"
    (pack_root / "scenarios").mkdir(parents=True)
    monkeypatch.setenv("LOOPSMITH_BENCHMARKS", str(pack_root))
    assert resolve_pack_root() == pack_root