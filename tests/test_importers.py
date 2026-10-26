import json

import pytest

from loopsmith.traces import importers
from loopsmith.traces.importers import ImportFormatError


def test_ingest_canonical(populated_store):
    traces = populated_store.list_traces()
    assert len(traces) == 2
    assert all(t.source == "loopsmith-jsonl" for t in traces)
    s1_events = populated_store.trace_events(traces[0].id)
    assert s1_events[0].kind == "user.message"
    assert s1_events[0].payload["text"].startswith("Fix the failing auth tests")


def test_reimport_is_noop(store, tmp_path):
    from conftest import EXAMPLES

    path = EXAMPLES / "acme-api-session1.jsonl"
    first = importers.ingest(store, path, "acme-api")
    assert not first.duplicate and first.events == 11
    second = importers.ingest(store, path, "acme-api")
    assert second.duplicate
    assert second.trace_id == first.trace_id
    assert len(store.list_traces()) == 1


def test_trace_id_is_content_hash(store, tmp_path):
    from conftest import EXAMPLES

    path = EXAMPLES / "acme-api-session1.jsonl"
    parsed = importers.parse_file(path, "acme-api")
    assert parsed.trace.id.startswith("t")
    assert parsed.trace.id == importers.parse_file(path, "other").trace.id


def test_generic_jsonl_mapping(store, tmp_path):
    log = tmp_path / "generic.jsonl"
    lines = [
        {"role": "system", "content": "You are a coding agent."},
        {"role": "user", "content": "Run the linter please."},
        {"role": "assistant", "content": "Running the linter now.",
         "tool_calls": [{"id": "c1", "function": {"name": "bash",
                                                  "arguments": '{"command": "make lint"}'}}]},
        {"role": "tool", "content": "exit 0, no issues"},
        {"role": "assistant", "content": "Lint is clean."},
    ]
    log.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    result = importers.ingest(store, log, "demo", "auto")
    assert result.source == "generic-jsonl"
    assert result.skipped == 1  # the system message
    events = store.trace_events(result.trace_id)
    assert [e.kind for e in events] == [
        "user.message", "assistant.message", "tool.call", "tool.result", "assistant.message",
    ]
    assert events[2].payload["name"] == "bash"
    assert events[2].raw is not None  # provenance preserved


def test_sniff_rejects_garbage(store, tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"hello": "world"}\n', encoding="utf-8")
    with pytest.raises(ImportFormatError):
        importers.parse_file(bad, "p")


def test_invalid_json_fails_fast(store, tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"kind": "user.message"}\nnot json\n', encoding="utf-8")
    with pytest.raises(ImportFormatError):
        importers.parse_file(bad, "p", "loopsmith")


def test_unknown_format_rejected(store, tmp_path):
    from conftest import EXAMPLES

    with pytest.raises(ImportFormatError):
        importers.parse_file(EXAMPLES / "acme-api-session1.jsonl", "p", "nope")


def test_explicit_seqs_are_normalized(store, tmp_path):
    path = tmp_path / "seq.jsonl"
    lines = [
        {"kind": "user.message", "seq": 10, "payload": {"text": "a"}},
        {"kind": "assistant.message", "seq": 20, "payload": {"text": "b"}},
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    parsed = importers.parse_file(path, "p", "loopsmith")
    assert [e.seq for e in parsed.events] == [1, 2]