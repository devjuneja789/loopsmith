import json
import shutil

import pytest

from conftest import FakeLLM
from loopsmith.eval.agent import SandboxError, _safe_path, run_agent


def _sandbox(tmp_path, scenario):
    sandbox = tmp_path / "sandbox"
    shutil.copytree(scenario.workspace, sandbox)
    return sandbox


def _fix_add():
    return json.dumps({
        "tool": "write_file",
        "args": {"path": "app/mathx.py",
                 "content": "def add(a, b):\n    return a + b\n"},
    })


def _finish():
    return json.dumps({"tool": "finish", "args": {"summary": "fixed add"}})


def test_agent_reads_writes_and_finishes(tmp_path, tiny_pack):
    scenario = tiny_pack.scenarios[0]
    sandbox = _sandbox(tmp_path, scenario)
    llm = FakeLLM([
        json.dumps({"tool": "list_dir", "args": {"path": "."}}),
        json.dumps({"tool": "read_file", "args": {"path": "app/mathx.py"}}),
        _fix_add(),
        _finish(),
    ])
    run = run_agent(llm, scenario, "", sandbox)
    assert run.finished
    assert run.turns == 4
    assert "return a + b" in (sandbox / "app" / "mathx.py").read_text(encoding="utf-8")
    assert run.tokens_in == 40  # 4 calls x 10 prompt tokens
    assert [t["tool"] for t in run.transcript] == [
        "list_dir", "read_file", "write_file", "finish"]


def test_run_command_allowed_and_blocks_others(tmp_path, tiny_pack):
    scenario = tiny_pack.scenarios[0]
    sandbox = _sandbox(tmp_path, scenario)
    llm = FakeLLM([
        json.dumps({"tool": "run_command", "args": {"command": "rm -rf ."}}),
        json.dumps({"tool": "run_command", "args": {"command": "python -m pytest -q"}}),
        _finish(),
    ])
    run = run_agent(llm, scenario, "", sandbox)
    assert "not allowed" in run.transcript[0]["observation"]
    assert "exit=" in run.transcript[1]["observation"]


def test_path_traversal_is_blocked(tmp_path, tiny_pack):
    scenario = tiny_pack.scenarios[0]
    sandbox = _sandbox(tmp_path, scenario)
    llm = FakeLLM([
        json.dumps({"tool": "write_file",
                    "args": {"path": "../escape.txt", "content": "x"}}),
        _finish(),
    ])
    run = run_agent(llm, scenario, "", sandbox)
    assert "escapes the workspace" in run.transcript[0]["observation"]
    assert not (tmp_path / "escape.txt").exists()


def test_safe_path_rejects_absolute_escape(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    with pytest.raises(SandboxError):
        _safe_path(workspace, "../outside.txt")


def test_non_json_reply_yields_error_observation(tmp_path, tiny_pack):
    scenario = tiny_pack.scenarios[0]
    sandbox = _sandbox(tmp_path, scenario)
    run = run_agent(FakeLLM(["I will now fix the bug.", "Still chatting."]),
                    scenario, "", sandbox, max_turns=2)
    assert "JSON object" in run.transcript[0]["observation"]
    assert not run.finished


def test_max_turns_stops_the_loop(tmp_path, tiny_pack):
    scenario = tiny_pack.scenarios[0]
    sandbox = _sandbox(tmp_path, scenario)
    llm = FakeLLM([json.dumps({"tool": "list_dir", "args": {"path": "."}})] * 2)
    run = run_agent(llm, scenario, "", sandbox, max_turns=2)
    assert run.turns == 2
    assert not run.finished
    assert len(llm.calls) == 2


def test_harness_pack_is_in_the_system_prompt(tmp_path, tiny_pack):
    scenario = tiny_pack.scenarios[0]
    sandbox = _sandbox(tmp_path, scenario)
    llm = FakeLLM([_finish()])
    run_agent(llm, scenario, "# Harness guidance\n\nUSE THE HINT", sandbox)
    system = llm.calls[0][0]["content"]
    assert "USE THE HINT" in system
    assert "Fix add" in system