"""Shared test setup: every test runs against a temp DATA_DIR, mock sources, no keys, no latency.
Never touches the real data/ dir and never calls a paid API."""

from __future__ import annotations

import os
import tempfile

import pytest

# Before any app import (collection time): keep import-time settings off the real data dir.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="creator-scout-test-")
os.environ["SOURCE_MODE"] = "mock"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["LLM_PROVIDER"] = ""
# Provider tuning a developer may have in .env / the shell: tests assume the documented defaults.
_LLM_DEFAULTS = ("LLM_BASE_URL", "OPENROUTER_BASE_URL", "OPENROUTER_MODEL_CHAT", "OPENROUTER_MODEL_BULK",
                 "OPENROUTER_FALLBACK_MODELS", "OPENROUTER_DATA_COLLECTION", "OPENROUTER_BULK_TASKS",
                 "OPENROUTER_TASKS", "LLM_REQUEST_BUDGET")
for _name in _LLM_DEFAULTS:
    os.environ[_name] = ""
os.environ["APIFY_TOKEN"] = ""
os.environ["MOCK_LATENCY"] = "0"

from app import config  # noqa: E402
from app.llm import budget  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SOURCE_MODE", "mock")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("LLM_PROVIDER", "")
    for name in _LLM_DEFAULTS:
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("APIFY_TOKEN", "")
    monkeypatch.setenv("MOCK_LATENCY", "0")
    config.reload_settings()
    budget.reset_budget()   # the LLM request counter is per process: never leak it between tests
    yield config.get_settings()
    config.reload_settings()
    budget.reset_budget()
