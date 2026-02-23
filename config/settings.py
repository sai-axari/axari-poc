"""Environment configuration for the Axari POC."""
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

# LLM Provider: "openrouter" or "anthropic"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openrouter").lower()

# API Keys
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://localhost:5432/axari")

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Agent config
MAX_OBSERVATION_LENGTH = int(os.getenv("MAX_OBSERVATION_LENGTH", "10000"))
MAX_REACT_ITERATIONS = int(os.getenv("MAX_REACT_ITERATIONS", "15"))
MAX_WORKER_ITERATIONS = int(os.getenv("MAX_WORKER_ITERATIONS", "8"))

# Tool result cache
TOOL_CACHE_TTL = int(os.getenv("TOOL_CACHE_TTL", "300"))              # 5 min default
TOOL_CACHE_MAX_ENTRIES = int(os.getenv("TOOL_CACHE_MAX_ENTRIES", "100"))
