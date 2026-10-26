"""Runtime configuration (env-driven; no config files to babysit)."""

import os

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


class LLMConfig(BaseModel):
    """An OpenAI-compatible chat-completions endpoint. Never Alan-internal."""

    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)


def load_llm_config() -> LLMConfig:
    return LLMConfig(
        base_url=os.environ.get("LOOPSMITH_LLM_BASE_URL"),
        api_key=os.environ.get("LOOPSMITH_LLM_API_KEY"),
        model=os.environ.get("LOOPSMITH_LLM_MODEL"),
    )
