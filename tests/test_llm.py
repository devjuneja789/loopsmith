import io
import json
import urllib.error

import pytest

from loopsmith.config import LLMConfig
from loopsmith.eval import llm as llm_mod
from loopsmith.eval.llm import LLMClient, LLMError, extract_json


def test_extract_json_plain():
    assert extract_json('{"tool": "finish", "args": {}}') == {"tool": "finish", "args": {}}


def test_extract_json_fenced():
    text = '```json\n{"tool": "read_file", "args": {"path": "a.py"}}\n```'
    assert extract_json(text)["tool"] == "read_file"


def test_extract_json_from_prose():
    text = 'Sure. Here is my action:\n{"tool": "list_dir", "args": {"path": "."}}\nThanks.'
    assert extract_json(text)["tool"] == "list_dir"


def test_extract_json_invalid_returns_empty():
    assert extract_json("no json here") == {}
    assert extract_json("{broken") == {}
    assert extract_json("[1, 2, 3]") == {}


def test_client_requires_config():
    with pytest.raises(LLMError):
        LLMClient(LLMConfig())


def _fake_response(payload):
    class FakeResponse:
        def read(self):
            return json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    return FakeResponse()


def test_client_parses_completion(monkeypatch):
    payload = {
        "choices": [{"message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    }
    monkeypatch.setattr(llm_mod.urllib.request, "urlopen",
                        lambda request, timeout: _fake_response(payload))
    client = LLMClient(LLMConfig(base_url="https://example.test/v1",
                                 api_key="k", model="m"))
    result = client.chat([{"role": "user", "content": "hi"}])
    assert result.text == "hello"
    assert result.usage["prompt_tokens"] == 7


def _http_error(code, body=b'{"error": "x"}'):
    return urllib.error.HTTPError("https://example.test", code, "err", None,
                                  io.BytesIO(body))


def test_rate_limit_is_explained(monkeypatch):
    def boom(request, timeout):
        raise _http_error(429)

    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", boom)
    client = LLMClient(LLMConfig(base_url="https://example.test", api_key="k",
                                 model="m"), retries=0)
    with pytest.raises(LLMError, match="rate limited"):
        client.chat([{"role": "user", "content": "hi"}])


def test_unauthorized_is_explained(monkeypatch):
    def boom(request, timeout):
        raise _http_error(401)

    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", boom)
    client = LLMClient(LLMConfig(base_url="https://example.test", api_key="k",
                                 model="m"), retries=0)
    with pytest.raises(LLMError, match="unauthorized"):
        client.chat([{"role": "user", "content": "hi"}])


def test_unknown_model_is_explained(monkeypatch):
    def boom(request, timeout):
        raise _http_error(404)

    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", boom)
    client = LLMClient(LLMConfig(base_url="https://example.test", api_key="k",
                                 model="nope"), retries=0)
    with pytest.raises(LLMError, match="not found"):
        client.chat([{"role": "user", "content": "hi"}])


def test_server_error_retries_then_fails(monkeypatch):
    calls = {"n": 0}

    def boom(request, timeout):
        calls["n"] += 1
        raise _http_error(500)

    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", boom)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda seconds: None)
    client = LLMClient(LLMConfig(base_url="https://example.test", api_key="k",
                                 model="m"), retries=2)
    with pytest.raises(LLMError, match="HTTP 500"):
        client.chat([{"role": "user", "content": "hi"}])
    assert calls["n"] == 3