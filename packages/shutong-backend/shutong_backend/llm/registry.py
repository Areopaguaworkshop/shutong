"""Provider/model registry for the Shutong daemon."""

from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List


MODELS_DEV_URL = "https://models.dev/api.json"
CACHE_TTL_SECONDS = 24 * 60 * 60


def _cache_path() -> Path:
    storage = os.environ.get("SHUTONG_STORAGE_DIR") or os.environ.get("CITEINDEX_STORAGE_DIR") or ".shutong"
    return Path(storage) / "models.dev.json"


def _fallback_catalog() -> Dict[str, Any]:
    return {
        "providers": [
            {"id": "ollama", "name": "Ollama", "models": ["glm-5.3-flash:cloud", "deepseek-v4-pro:cloud", "qwen3.5:cloud", "qwen3"]},
            {"id": "anthropic", "name": "Anthropic", "models": []},
            {"id": "openai", "name": "OpenAI", "models": []},
        ],
        "source": "fallback",
    }


def _read_cache(path: Path) -> Dict[str, Any] | None:
    if not path.exists() or time.time() - path.stat().st_mtime > CACHE_TTL_SECONDS:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _fetch_catalog(path: Path) -> Dict[str, Any] | None:
    try:
        with urllib.request.urlopen(MODELS_DEV_URL, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data
    except Exception:
        return None


def _models_from_models_dev(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    providers: List[Dict[str, Any]] = []
    for provider_id in ("anthropic", "openai"):
        provider = raw.get(provider_id) or {}
        models = provider.get("models") or {}
        providers.append({
            "id": provider_id,
            "name": provider.get("name") or provider_id.title(),
            "models": sorted(models.keys()),
        })
    providers.insert(0, _fallback_catalog()["providers"][0])
    return providers


def list_providers(force_refresh: bool = False) -> Dict[str, Any]:
    """Return configured providers and a cached models.dev catalog when available."""
    path = _cache_path()
    raw = None if force_refresh else _read_cache(path)
    source = "cache" if raw else "network"
    raw = raw or _fetch_catalog(path)
    if not raw:
        return _fallback_catalog()
    return {"providers": _models_from_models_dev(raw), "source": source}


def parse_model(model_string: str, default_provider: str = "ollama") -> tuple[str, str]:
    if "/" in model_string:
        return model_string.split("/", 1)
    return default_provider, model_string
