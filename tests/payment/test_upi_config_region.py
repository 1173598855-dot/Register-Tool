"""``_upi_retarget_region``: a thin wrapper whose failure means "leave the proxy alone".

Why this exists
---------------
The wrapper exists so ``upi_link/config`` never imports ``proxy.entry`` at module
scope (the payment flow is import-lazy by design) and so a provider that does not use
region tags is untouched. Its handler used to catch ``Exception``, which made "the
parser rejected this template" and "``retarget_region`` has a bug" produce the same
answer: the original proxy, silently.

Lane-level template: ``docs/audits/records/broad-except-boundary-2026-11-11.md`` §1.3.
The caught set is the lazy import plus the parser's own documented rejects
(``TypeError``/``ValueError`` from ``urlsplit``); a defect now propagates.
"""

from __future__ import annotations

import pytest

from sms_tool.proxy import entry
from sms_tool.upi_link import config

TAGGED = "http://region-HK-sess-1:pw@exit:8080"


def test_a_region_tagged_proxy_is_retargeted():
    assert config._upi_retarget_region(TAGGED, "us") == "http://region-US-sess-1:pw@exit:8080"


def test_an_untagged_proxy_is_left_alone():
    plain = "http://user:pass@exit:8080"

    assert config._upi_retarget_region(plain, "US") == plain


def test_a_bad_country_code_short_circuits_before_the_import():
    assert config._upi_retarget_region(TAGGED, "USA") == TAGGED


def test_a_parser_rejection_keeps_the_original_proxy(monkeypatch):
    def boom(*_args, **_kwargs):
        raise ValueError("template the parser cannot read")

    monkeypatch.setattr(entry, "retarget_region", boom)

    assert config._upi_retarget_region(TAGGED, "US") == TAGGED


def test_a_defect_in_the_parser_propagates(monkeypatch):
    """A bug used to be indistinguishable from a template this module leaves alone."""

    def boom(*_args, **_kwargs):
        raise RuntimeError("bug in retarget_region")

    monkeypatch.setattr(entry, "retarget_region", boom)

    with pytest.raises(RuntimeError):
        config._upi_retarget_region(TAGGED, "US")
