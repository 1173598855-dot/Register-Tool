"""Tests for the ASCII trust-store bridge (``sms_tool/kernel/ca_bundle.py``).

The defect this guards is invisible on CI: libcurl opens its CA bundle through
the process ANSI code page, so a ``cacert.pem`` under a path with non-ASCII
characters fails to load and every HTTPS request dies with ``curl: (77)``. CI
checks out to an ASCII path, so the bridge is a no-op there and nothing notices
if it silently stops working. These tests pin both directions:

* the bridge does **nothing** when the bundle path is already ASCII, so a healthy
  machine pays no file copy and no environment mutation;
* it copies the exact bytes to an ASCII location and points the standard CA
  variables at that copy when it is not;
* every unreachable case (no bundle, missing file, no ASCII root) returns ``None``
  and leaves the environment alone — the bridge must never make a working setup
  worse.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sms_tool.kernel import ca_bundle

CA_VARS = ca_bundle.CA_ENV_VARS


@pytest.fixture(autouse=True)
def _clear_ca_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """A leftover CA variable in the real environment must not affect a case."""
    for name in CA_VARS:
        monkeypatch.delenv(name, raising=False)


def write_bundle(
    directory: Path, payload: bytes = b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "cacert.pem"
    target.write_bytes(payload)
    return target


def test_an_ascii_bundle_is_left_alone(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path / "ascii")

    assert ca_bundle.install_ascii_ca_bundle(bundle) is None
    assert all(os.environ.get(name) is None for name in CA_VARS)


def test_a_non_ascii_bundle_is_bridged_to_an_ascii_copy(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path / "要用到的" / "注册机")

    bridged = ca_bundle.install_ascii_ca_bundle(bundle, target_root=tmp_path / "ascii-root")

    assert bridged is not None
    assert bridged.isascii()
    assert Path(bridged).read_bytes() == bundle.read_bytes()
    for name in CA_VARS:
        assert os.environ[name] == bridged


def test_the_bridge_is_idempotent(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path / "要用到的")
    first = ca_bundle.install_ascii_ca_bundle(bundle, target_root=tmp_path / "root")

    second = ca_bundle.install_ascii_ca_bundle(bundle, target_root=tmp_path / "root")

    assert first == second
    assert len(list((tmp_path / "root" / ca_bundle.CA_DIR_NAME).iterdir())) == 1


def test_a_changed_bundle_lands_on_a_new_digest_name(tmp_path: Path) -> None:
    """A certifi upgrade must not keep serving the old trust store."""
    root = tmp_path / "root"
    first = ca_bundle.install_ascii_ca_bundle(write_bundle(tmp_path / "要用到的"), target_root=root)
    second = ca_bundle.install_ascii_ca_bundle(
        write_bundle(tmp_path / "要用到的", b"-----BEGIN CERTIFICATE-----\nOTHER\n-----END CERTIFICATE-----\n"),
        target_root=root,
    )

    assert first != second


def test_an_existing_ascii_operator_value_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An operator who already pointed the variable somewhere valid keeps it."""
    keep = str(tmp_path / "operator.pem")
    monkeypatch.setenv("CURL_CA_BUNDLE", keep)
    bundle = write_bundle(tmp_path / "注册机")

    ca_bundle.install_ascii_ca_bundle(bundle, target_root=tmp_path / "root")

    assert os.environ["CURL_CA_BUNDLE"] == keep
    assert os.environ["REQUESTS_CA_BUNDLE"].isascii()


@pytest.mark.parametrize("bundle", [None, "does-not-exist.pem"])
def test_an_unusable_bundle_changes_nothing(bundle: str | None) -> None:
    assert ca_bundle.install_ascii_ca_bundle(bundle) is None
    assert all(os.environ.get(name) is None for name in CA_VARS)


def test_no_ascii_root_available_is_not_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A profile path with non-ASCII characters must not turn into a crash."""
    non_ascii_root = tmp_path / "无可用目录"
    non_ascii_root.mkdir()
    monkeypatch.setattr(ca_bundle, "ascii_candidate_roots", lambda environ=None: (non_ascii_root,))
    bundle = write_bundle(tmp_path / "注册机")

    assert ca_bundle.install_ascii_ca_bundle(bundle) is None
    assert all(os.environ.get(name) is None for name in CA_VARS)


def test_candidate_roots_are_ascii_only(monkeypatch: pytest.MonkeyPatch) -> None:
    roots = ca_bundle.ascii_candidate_roots({"ProgramData": r"D:\程序数据", "SystemDrive": "E:"})

    assert roots
    assert all(str(root).isascii() for root in roots)
    assert Path(r"D:\程序数据") not in roots
