"""Runtime configuration (env-driven; optional .env for convenience)."""

import os
from pathlib import Path

from pydantic import BaseModel

DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Free-tier coding models on OpenRouter, checked Oct 2026. The primary pick is
# a dedicated agentic-coding model with a stable free endpoint; the others are
# fallbacks if the roster rotates. Free tier is rate-limited (~50 req/day
# without $10 lifetime credits) -- P1 eval defaults to N=1 runs + caching.
RECOMMENDED_LLM_MODELS = [
    "cohere/north-mini-code:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "thinkingmachines/inkling-small:free",
]

DOTENV_SKIP = "LOOPSMITH_SKIP_DOTENV"


def load_dotenv(path: Path | str | None = None) -> bool:
    """Load KEY=VALUE pairs from .env without overriding real env vars.

    Tolerates `export KEY=...` and `$env:KEY = "..."` lines so a pasted
    PowerShell snippet in .env still works. Tests and the model-free demo
    set LOOPSMITH_SKIP_DOTENV=1 to stay hermetic.
    """
    if os.environ.get(DOTENV_SKIP) == "1":
        return False
    env_path = Path(path) if path else Path(".env")
    if not env_path.is_file():
        return False
    loaded = False
    for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        for prefix in ("export ", "$env:"):
            if key.startswith(prefix):
                key = key[len(prefix):].strip()
        if not key or key in os.environ:
            continue
        value = value.strip().strip('"').strip("'")
        if not value:
            continue
        os.environ[key] = value
        loaded = True
    return loaded


class LLMConfig(BaseModel):
    """An OpenAI-compatible chat-completions endpoint."""

    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)


def load_llm_config() -> LLMConfig:
    load_dotenv()
    return LLMConfig(
        base_url=os.environ.get("LOOPSMITH_LLM_BASE_URL"),
        api_key=os.environ.get("LOOPSMITH_LLM_API_KEY"),
        model=os.environ.get("LOOPSMITH_LLM_MODEL"),
    )
