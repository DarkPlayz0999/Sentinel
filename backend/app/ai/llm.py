"""Mistral chat client. Optional: the whole product works without it.

Configuration (environment):
    MISTRAL_API_KEY              enables the AI. Unset -> built-in summaries only.
    SENTINEL_LLM_MODEL           default "ministral-8b-latest" (fast, on the free tier)
    SENTINEL_LLM_FALLBACK_MODEL  default "mistral-small-latest": used when the main
                                 model stays rate-limited or is not on the plan
    SENTINEL_LLM_BASE_URL        default "https://api.mistral.ai/v1" (any server
                                 speaking the same /chat/completions API works)
    SENTINEL_AI                  "0" switches the AI off even when a key is set

Data leaves the machine when this is on: the fact sheet for the page being
explained is sent to the configured endpoint. The fact sheets never contain
simulator ground truth in BLIND mode (see facts.py), and never an API key or
file path. The key itself is read from the environment only - never written
to the database, a log line or a response.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import httpx

__all__ = ["LLMConfig", "LLMError", "config", "chat"]


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    fallback_model: str
    base_url: str
    api_key: str
    timeout_s: float = 25.0

    @property
    def enabled(self) -> bool:
        return self.provider == "mistral" and bool(self.api_key)

    def public(self) -> dict:
        return {"provider": self.provider if self.enabled else "none",
                "model": self.model if self.enabled else None,
                "fallback_model": self.fallback_model if self.enabled else None,
                "base_url": self.base_url if self.enabled else None,
                "enabled": self.enabled,
                "data_leaves_machine": self.enabled,
                "how_to_enable": None if self.enabled else
                "Set MISTRAL_API_KEY (and optionally SENTINEL_LLM_MODEL) before starting the API."}


def config() -> LLMConfig:
    key = os.environ.get("MISTRAL_API_KEY", "").strip()
    off = os.environ.get("SENTINEL_AI", "1").strip().lower() in {"0", "false", "off", "no"}
    return LLMConfig(
        provider="none" if off else "mistral",
        model=os.environ.get("SENTINEL_LLM_MODEL", "ministral-8b-latest"),
        fallback_model=os.environ.get("SENTINEL_LLM_FALLBACK_MODEL", "mistral-small-latest"),
        base_url=os.environ.get("SENTINEL_LLM_BASE_URL", "https://api.mistral.ai/v1").rstrip("/"),
        api_key=key,
    )


def _once(cfg: LLMConfig, model: str, messages, temperature, max_tokens) -> httpx.Response:
    return httpx.post(f"{cfg.base_url}/chat/completions",
                      json={"model": model, "messages": messages,
                            "temperature": temperature, "max_tokens": max_tokens},
                      headers={"Authorization": f"Bearer {cfg.api_key}",
                               "Content-Type": "application/json"},
                      timeout=cfg.timeout_s)


def chat(messages: list[dict], *, temperature: float = 0.1, max_tokens: int = 600,
         cfg: LLMConfig | None = None, meta: dict | None = None) -> str:
    """One chat completion. Raises LLMError when no model could answer.

    Tries the main model (backing off on 429 / 5xx), then the fallback model.
    ``meta``, if given, receives {"model": <the model that answered>}.
    """
    cfg = cfg or config()
    if not cfg.enabled:
        raise LLMError("AI is not configured (MISTRAL_API_KEY unset)")
    models = [cfg.model] + ([cfg.fallback_model] if cfg.fallback_model != cfg.model else [])
    last = "AI service failed"
    for model in models:
        for delay in (0.0, 1.5, 3.0):
            if delay:
                time.sleep(delay)
            try:
                r = _once(cfg, model, messages, temperature, max_tokens)
            except httpx.HTTPError as exc:
                last = f"cannot reach the AI service ({type(exc).__name__})"
                continue
            if r.status_code == 200:
                try:
                    text = r.json()["choices"][0]["message"]["content"].strip()
                except (KeyError, IndexError, ValueError) as exc:
                    raise LLMError("AI service returned an unreadable answer") from exc
                if meta is not None:
                    meta["model"] = model
                return text
            last = f"{model} returned {r.status_code}"
            if r.status_code in (401,):
                raise LLMError("the AI key was refused (401)")
            if r.status_code in (403, 404):
                break                  # not on this plan / unknown model: try the fallback
            if r.status_code not in (429, 500, 502, 503, 504):
                break
    raise LLMError(last)
