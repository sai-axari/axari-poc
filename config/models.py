"""Multi-model configuration for the Axari POC agent system."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from config.settings import LLM_PROVIDER

# Model names differ between providers:
#   OpenRouter: "anthropic/claude-sonnet-4"
#   Anthropic:  "claude-sonnet-4-20250514"
_MODEL_MAP = {
    "openrouter": {
        "sonnet": "anthropic/claude-sonnet-4.6",
    },
    "anthropic": {
        "sonnet": "claude-sonnet-4-20250514",
    },
}


def _model(alias: str) -> str:
    """Resolve a model alias to the correct ID for the active provider."""
    return _MODEL_MAP[LLM_PROVIDER][alias]


MODEL_CONFIGS = {
    "orchestrator": {
        "provider": LLM_PROVIDER,
        "model": _model("sonnet"),
        "max_tokens": 16000,
        "temperature": 1.0,  # Required when using extended thinking
        "thinking": {"type": "enabled", "budget_tokens": 4000},
    },
    "worker": {
        "provider": LLM_PROVIDER,
        "model": _model("sonnet"),
        "max_tokens": 10000,
        "temperature": 0,
    },
}


@dataclass
class TenantConfig:
    """Configuration for a specific tenant."""
    tenant_id: str
    allowed_integrations: list[str] = None
    integration_constraints: dict = None
