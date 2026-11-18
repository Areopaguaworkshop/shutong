"""Shutong LLM Provider Abstraction.

Supports ollama, openai, and anthropic providers with a unified interface.
Model string format: {provider}/{model} (e.g., "ollama/qwen3.5:cloud", "anthropic/claude-sonnet-4-6").
"""

from shutong_backend.llm.provider import LLMProvider, get_provider, get_llm

__all__ = ["LLMProvider", "get_provider", "get_llm"]