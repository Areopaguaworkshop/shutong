"""LLM Provider Abstraction — unified interface for ollama, openai, and anthropic."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def complete(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> str:
        """Send messages and return the assistant response text."""

    @abstractmethod
    def stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> Iterator[str]:
        """Send messages and yield response tokens."""

    def invoke(self, prompt: str, model: str = "", temperature: float = 0.1, max_tokens: int = 4096) -> str:
        """Simple invoke interface — sends a single user message and returns text."""
        return self.complete(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )


class OllamaProvider(LLMProvider):
    """Ollama local LLM provider."""

    def __init__(self, base_url: Optional[str] = None) -> None:
        self.base_url = base_url or os.environ.get("SHUTONG_LLM_BASE_URL") or "http://localhost:11434"

    def complete(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> str:
        model_name = model.removeprefix("ollama/")
        try:
            import ollama

            client = ollama.Client(host=self.base_url)
            response = client.chat(
                model=model_name,
                messages=messages,
                options={"temperature": temperature, "num_predict": max_tokens},
            )
            return response.get("message", {}).get("content", "")
        except ImportError:
            logger.warning("ollama package not available, falling back to subprocess")
            return self._subprocess_complete(messages, model_name, temperature, max_tokens)

    def stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> Iterator[str]:
        model_name = model.removeprefix("ollama/")
        try:
            import ollama

            client = ollama.Client(host=self.base_url)
            for chunk in client.chat(
                model=model_name,
                messages=messages,
                options={"temperature": temperature, "num_predict": max_tokens},
                stream=True,
            ):
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield content
        except ImportError:
            text = self._subprocess_complete(messages, model_name, temperature, max_tokens)
            yield text

    def _subprocess_complete(
        self,
        messages: List[Dict[str, str]],
        model_name: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        prompt = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        try:
            result = subprocess.run(
                ["ollama", "run", model_name, prompt],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                stderr = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", result.stderr).strip()
                raise RuntimeError(stderr or f"ollama exited with code {result.returncode}")
            return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            raise RuntimeError(str(exc)) from exc


class OpenAIProvider(LLMProvider):
    """OpenAI LLM provider."""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url

    def complete(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> str:
        from openai import OpenAI

        model_name = model.removeprefix("openai/")
        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    def stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> Iterator[str]:
        from openai import OpenAI

        model_name = model.removeprefix("openai/")
        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        for chunk in client.chat.completions.create(
            model=model_name,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        ):
            content = chunk.choices[0].delta.content or ""
            if content:
                yield content


class AnthropicProvider(LLMProvider):
    """Anthropic LLM provider."""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None) -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.base_url = base_url

    def complete(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> str:
        from anthropic import Anthropic

        model_name = model.removeprefix("anthropic/")
        client = Anthropic(api_key=self.api_key, base_url=self.base_url)
        # Anthropic API separates system from messages
        system_msg = ""
        user_messages: List[Dict[str, str]] = []
        for m in messages:
            if m["role"] == "system":
                system_msg += m["content"] + "\n"
            else:
                user_messages.append(m)

        response = client.messages.create(
            model=model_name,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_msg.strip() or None,
            messages=user_messages,  # type: ignore[arg-type]
        )
        return response.content[0].text if response.content else ""

    def stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> Iterator[str]:
        from anthropic import Anthropic

        model_name = model.removeprefix("anthropic/")
        client = Anthropic(api_key=self.api_key, base_url=self.base_url)
        system_msg = ""
        user_messages: List[Dict[str, str]] = []
        for m in messages:
            if m["role"] == "system":
                system_msg += m["content"] + "\n"
            else:
                user_messages.append(m)

        with client.messages.stream(
            model=model_name,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_msg.strip() or None,
            messages=user_messages,  # type: ignore[arg-type]
        ) as stream:
            for text in stream.text_stream:
                yield text


# ── Factory ──────────────────────────────────────────────────────────────

_PROVIDERS: Dict[str, type] = {
    "ollama": OllamaProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
}


def get_provider(provider_name: str) -> LLMProvider:
    """Return an LLMProvider instance for the given provider name."""
    provider_cls = _PROVIDERS.get(provider_name)
    if provider_cls is None:
        raise ValueError(f"Unknown LLM provider: {provider_name}. Available: {list(_PROVIDERS.keys())}")
    return provider_cls()


def _parse_model_string(model_string: str) -> tuple[str, str]:
    """Parse 'provider/model' string into (provider, model)."""
    if "/" in model_string:
        provider, model = model_string.split("/", 1)
        return provider, model
    return "ollama", model_string


def get_llm(model_string: str, temperature: float = 0.1, max_tokens: int = 4096) -> LLMProvider:
    """Get an LLM provider configured for the given model string.

    Model string format: 'provider/model' (e.g., 'ollama/qwen3.5:cloud', 'anthropic/claude-sonnet-4-6').
    Falls back to ollama if no provider prefix is given.
    """
    provider_name, model_name = _parse_model_string(model_string)
    provider = get_provider(provider_name)
    # Store model name on the provider for convenience
    provider._default_model = model_name  # type: ignore[attr-defined]
    provider._temperature = temperature  # type: ignore[attr-defined]
    provider._max_tokens = max_tokens  # type: ignore[attr-defined]
    return provider


def ollama_model_available(model_name: str, base_url: str = "") -> bool:
    """Return True if the model is already pulled locally.

    ``ollama run <model>`` auto-pulls a missing model and blocks for minutes,
    so callers must check availability first and fall back deterministically.
    Uses the /api/tags endpoint (stdlib only, no ollama package needed).
    """
    base_url = base_url or os.environ.get("SHUTONG_LLM_BASE_URL") or "http://localhost:11434"
    try:
        import urllib.request

        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=3) as resp:
            data = json.loads(resp.read().decode())
        names = {m.get("name", "") for m in data.get("models", [])}
        if model_name in names:
            return True
        # ollama defaults a bare name to :latest
        if ":" not in model_name and f"{model_name}:latest" in names:
            return True
        return False
    except Exception:
        return False
