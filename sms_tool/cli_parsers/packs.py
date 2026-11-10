"""Provider-pack management flags for ``cli.build_parser``.

Every registration architecture is a pack with its own manifest, version and
lifecycle hooks, so these three flags are the operator entry points for
inspecting, diagnosing and upgrading one without running a registration or
touching another pack.

Declaration only, per Rule 15: no dispatch, no validation, no provider imports.
"""

import argparse


def register(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--pack-list",
        action="store_true",
        help="List installed provider packs (registration architectures) and their capabilities, then exit",
    )
    parser.add_argument(
        "--pack-info",
        default=None,
        metavar="PACK_ID",
        help="Show one provider pack's manifest, namespaces and lifecycle hooks, then exit",
    )
    parser.add_argument(
        "--pack-verify",
        nargs="?",
        const="*",
        default=None,
        metavar="PACK_ID",
        help="Resolve every declared pack entrypoint and hook (all packs when no id is given), then exit",
    )
