"""The ``--pack-list --json`` payload the desktop renders from (Phase 5.1).

Why this exists
---------------
``SmsWorkbench.Contracts/PackCapabilities.cs`` decides which sidebar rows to hide
by reading three fields out of this payload: ``packs[].id``, ``packs[].enabled`` and
``packs[].capabilities``. Nothing in the C# test project can notice if the backend
renames or reshapes them -- it parses whatever it is given, and a shape change would
degrade silently to "gate nothing", which looks exactly like a healthy single-pack
install.

So the contract is pinned from the producing side, and the capability *names* are
pinned against ``sms_tool/packs/contracts.py``: the desktop hard-codes
``payment.link`` / ``mailbox.otp`` / ``account.health``, and those strings must stay
in the backend's vocabulary or the gate would compare against a name no manifest can
ever declare.
"""

from __future__ import annotations

import json
import types
from typing import Any

from sms_tool import cli
from sms_tool.packs import CAPABILITY_VOCABULARY


def _payload() -> dict[str, Any]:
    args = types.SimpleNamespace(
        pack_list=True,
        pack_info=None,
        pack_verify=None,
        json_output=True,
        desktop_ipc=False,
    )
    captured: list[str] = []

    def fake_print(text: str, *rest: Any, **kwargs: Any) -> None:
        captured.append(text)

    original = cli.safe_print
    cli.safe_print = fake_print
    try:
        assert cli._pack_management_command(args) == 0
    finally:
        cli.safe_print = original

    return json.loads("".join(captured))


def test_the_payload_has_the_three_fields_the_desktop_reads() -> None:
    payload = _payload()

    assert isinstance(payload["packs"], list) and payload["packs"], "the desktop needs at least one row"
    for pack in payload["packs"]:
        assert isinstance(pack["id"], str) and pack["id"], "PackCapabilities.FromPackList reads packs[].id"
        assert isinstance(pack["enabled"], bool), "it reads packs[].enabled to skip disabled packs"
        assert isinstance(pack["capabilities"], list), "it reads packs[].capabilities for the gate"
        assert all(isinstance(name, str) for name in pack["capabilities"])


def test_every_declared_capability_is_in_the_vocabulary() -> None:
    payload = _payload()

    declared = {name for pack in payload["packs"] for name in pack["capabilities"]}

    assert declared <= CAPABILITY_VOCABULARY, declared - CAPABILITY_VOCABULARY


def test_the_capabilities_the_desktop_gates_on_are_real_vocabulary() -> None:
    """The three names hard-coded in ``PackCapabilities.cs`` must exist here.

    If one were renamed in ``contracts.py``, the C# gate would compare against a
    string no manifest could declare and every gated row would disappear -- a
    failure mode that looks like a deliberate product decision.
    """
    gated = {"payment.link", "mailbox.otp", "account.health"}

    assert gated <= CAPABILITY_VOCABULARY, gated - CAPABILITY_VOCABULARY


def test_the_bundled_pack_declares_every_capability_the_shell_renders() -> None:
    """Today's single pack must keep every gated row: this is the no-regression pin."""
    payload = _payload()
    enabled = [pack for pack in payload["packs"] if pack["enabled"]]

    assert len(enabled) == 1, "the shipped build has exactly one enabled pack"
    assert {"payment.link", "mailbox.otp", "account.health"} <= set(enabled[0]["capabilities"])
