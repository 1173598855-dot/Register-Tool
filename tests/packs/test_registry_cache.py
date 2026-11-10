"""Tests for the ambient pack-registry cache.

Every capability dispatch resolves a registry. Without a cache that means reading
and validating every manifest again, which in a 100-account batch is 100 rounds of
JSON parsing for files that did not change. The cache must be invisible: identical
value while nothing changed, a rebuilt registry the moment a manifest does, and
never applied to the explicit roots a caller passed on purpose.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from sms_tool.packs import loader

MANIFEST = {
    "schema": "provider-pack.v2",
    "id": "cache.demo",
    "display_name": "Cache Demo",
    "version": "1.0.0",
    "api_version": "1",
    "status": "active",
    "capabilities": ["account.health"],
    "endpoints": {"api": "https://cache.test"},
    "entrypoints": {"health": "sms_tool.accounts.account_liveness:probe_account_liveness"},
    "hooks": {},
    "risk_signals": [],
}


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    loader.reset_registry_cache()
    yield
    loader.reset_registry_cache()


@pytest.fixture
def ambient_pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """One extra manifest reachable through the ambient search path."""
    pack_dir = tmp_path / "demo"
    pack_dir.mkdir()
    manifest = pack_dir / "manifest.json"
    manifest.write_text(json.dumps(MANIFEST), encoding="utf-8")
    monkeypatch.setenv(loader.EXTERNAL_PACK_PATH_ENV, str(tmp_path))
    return manifest


def test_the_ambient_registry_is_memoised(ambient_pack: Path) -> None:
    first = loader.load_registry()
    second = loader.load_registry()

    assert first is second
    assert "cache.demo" in first.ids()


def test_a_changed_manifest_rebuilds_the_registry(ambient_pack: Path) -> None:
    first = loader.load_registry()
    payload = json.loads(ambient_pack.read_text(encoding="utf-8"))
    payload["version"] = "1.0.1"
    ambient_pack.write_text(json.dumps(payload), encoding="utf-8")

    second = loader.load_registry()

    assert second is not first
    assert second.get("cache.demo").manifest.version == "1.0.1"


def test_explicit_roots_are_never_cached(tmp_path: Path) -> None:
    first = loader.load_registry(roots=(tmp_path,))
    second = loader.load_registry(roots=(tmp_path,))

    assert first is not second


def test_reset_drops_the_memoised_registry(ambient_pack: Path) -> None:
    first = loader.load_registry()

    loader.reset_registry_cache()

    assert loader.load_registry() is not first


def test_a_broken_manifest_is_not_memoised(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failure must not be cached: fixing the file then reloading has to work."""
    pack_dir = tmp_path / "demo"
    pack_dir.mkdir()
    manifest = pack_dir / "manifest.json"
    manifest.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv(loader.EXTERNAL_PACK_PATH_ENV, str(tmp_path))
    with pytest.raises(loader.PackManifestError):
        loader.load_registry()

    manifest.write_text(json.dumps(MANIFEST), encoding="utf-8")

    assert "cache.demo" in loader.load_registry().ids()
