"""Minimal OpenAI-compatible chat client (stdlib only, no SDK).

Any endpoint speaking POST /chat/completions works: OpenRouter, vLLM,
LM Studio, or ollama's compat layer. LoopSmith never assumes a
vendor-internal model API.
"""

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from loopsmith.config import LLMConfig


class LLMError(RuntimeError):
    """Transport/config failure; the message is user-facing."""


@dataclass
class ChatResult:
    text: str = ""
    usage: dict = field(default_factory=dict)
    raw: dict | None = None


class LLMClient:
    def __init__(self, config: LLMConfig, timeout: float = 120.0, retries: int = 2):
        if not config.configured:
            raise LLMError("model endpoint not configured (set LOOPSMITH_LLM_*)")
        self.config = config
        self.timeout = timeout
        self.retries = retries

    def chat(self, messages: list[dict], temperature: float = 0.0,
             max_tokens: int = 1200) -> ChatResult:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        data = self._post(payload)
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"malformed response from endpoint: {str(data)[:200]}") from exc
        return ChatResult(
            text=message.get("content") or "",
            usage=data.get("usage") or {},
            raw=data,
        )

    def _post(self, payload: dict) -> dict:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
            "HTTP-Referer": "https://github.com/loopsmith",
            "X-Title": "LoopSmith",
        }
        last_error = ""
        for attempt in range(self.retries + 1):
            request = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:400]
                if exc.code == 401:
                    raise LLMError("unauthorized: check LOOPSMITH_LLM_API_KEY") from exc
                if exc.code == 404:
                    raise LLMError(
                        f"model '{self.config.model}' not found at {self.config.base_url} "
                        "(check LOOPSMITH_LLM_MODEL)") from exc
                if exc.code == 429:
                    if attempt < self.retries:
                        time.sleep(2 ** attempt)
                        continue
                    raise LLMError(
                        "rate limited (429). Free OpenRouter tiers allow ~50 requests/day "
                        "without $10 lifetime credits: use --runs 1, fewer scenarios, or "
                        "add credits.") from exc
                if exc.code in (500, 502, 503, 504) and attempt < self.retries:
                    last_error = f"HTTP {exc.code}: {detail}"
                    time.sleep(2 ** attempt)
                    continue
                raise LLMError(f"HTTP {exc.code}: {detail}") from exc
            except urllib.error.URLError as exc:
                last_error = str(exc.reason)
                if attempt < self.retries:
                    time.sleep(2 ** attempt)
                    continue
                raise LLMError(f"cannot reach {url}: {last_error}") from exc
            except TimeoutError as exc:
                raise LLMError(f"timeout after {self.timeout}s talking to {url}") from exc
        raise LLMError(last_error or "request failed")


def extract_json(text: str) -> dict:
    """Best-effort extraction of the first JSON object in a model reply."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        end = -1 if (len(lines) > 1 and lines[-1].strip() == "```") else len(lines)
        stripped = "\n".join(lines[1:end])
    try:
        obj = json.loads(stripped)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    while start != -1:
        depth = 0
        for index in range(start, len(stripped)):
            char = stripped[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(stripped[start:index + 1])
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        pass
                    break
        start = stripped.find("{", start + 1)
    return {}