"""Provider factory: cache / apify modes must not crash while Kryštof's ApifyProvider is a stub."""

from __future__ import annotations

import pytest

from app.events import bind_emit
from app.models import DiscoveryQuery
from app.sources.factory import UnavailableProvider, apify_available, get_provider


@pytest.mark.parametrize("mode", ["cache", "apify"])
async def test_non_mock_modes_never_raise(mode, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import reload_settings

    reload_settings()
    provider = get_provider(mode)  # must not raise even though apify_provider.py is a stub
    logs: list[dict] = []

    async def emit(event: str, data: dict) -> None:
        if event == "log":
            logs.append(data)

    with bind_emit(emit):
        assert await provider.discover(DiscoveryQuery(keywords=["brno food"])) == []
        assert await provider.profiles(["x"], "instagram") == []
    if not apify_available():
        assert logs, "an unavailable provider must say why in the live log"


async def test_unavailable_provider_logs_and_returns_empty():
    p = UnavailableProvider("because")
    seen: list[str] = []

    async def emit(event: str, data: dict) -> None:
        seen.append(data["text"])

    with bind_emit(emit):
        assert await p.news("Jakub Horák") == []
    assert seen and "because" in seen[0]


@pytest.mark.parametrize("fill,expected", [("", True), ("1", False)])
def test_cache_mode_is_read_only_unless_opted_in(fill, expected, tmp_path, monkeypatch):
    """A token read from .env must not turn a replay cache miss into a paid live run."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APIFY_TOKEN", "apify_api_test_only")
    monkeypatch.setenv("CACHE_FILL_MISSES", fill)
    from app.config import reload_settings

    reload_settings()
    provider = get_provider("cache")
    if isinstance(getattr(provider, "inner", None), UnavailableProvider):
        expected = True
    assert provider.read_only is expected
    monkeypatch.delenv("APIFY_TOKEN")
    reload_settings()
