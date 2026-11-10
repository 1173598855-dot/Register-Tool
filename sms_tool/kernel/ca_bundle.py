"""ASCII-safe bridge for the TLS trust store.

Why this exists
---------------
``curl_cffi`` hands its bundled libcurl a CA file path, and libcurl opens it with
the process ANSI code page rather than UTF-16. A trust store that lives under a
path with non-ASCII characters -- ``C:\\Users\\…\\要用到的\\注册机\\…``, or simply a
Windows account name with Chinese characters, because ``certifi`` ships inside
``site-packages`` -- therefore fails to load and **every** HTTPS request dies
with::

    curl: (77) error adding trust anchors from locations:
      CAfile: …\\site-packages\\certifi\\cacert.pem CApath: none

Measured on 2026-11-10: the identical ``cacert.pem`` bytes load fine from an
ASCII path and fail from the non-ASCII one, so this is a path problem, not a
certifi-version problem. The workaround is to keep a copy at an ASCII location
and point the standard CA environment variables at it.

Scope and safety
----------------
* Standard library only -- this lives in ``kernel/`` and the kernel may not import
  application or third-party modules. The caller supplies the bundle path, which
  is why :func:`install_ascii_ca_bundle` takes it as an argument instead of
  importing ``certifi`` itself.
* **No-op in the normal case.** An ASCII path is returned untouched and no file
  is written, so a healthy machine pays one ``str.isascii()`` call.
* **Never makes things worse.** A missing bundle, an unreadable file or no ASCII
  candidate directory all return ``None`` and leave the environment alone; the
  process then behaves exactly as it did before this module existed.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from collections.abc import Mapping, MutableMapping
from pathlib import Path

#: The variables libcurl, requests and curl_cffi consult, in precedence order.
CA_ENV_VARS: tuple[str, ...] = ("CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE")

#: Subdirectory created under the first ASCII candidate root.
CA_DIR_NAME = "gpt-register-tool-ca"


def ascii_candidate_roots(environ: Mapping[str, str] | None = None) -> tuple[Path, ...]:
    """Directories that are usable even when the profile path is not.

    The system temp dir is first because it is the one location this code can
    almost always write to; ``ProgramData`` and the system drive follow because a
    Windows account name with non-ASCII characters also makes ``%LOCALAPPDATA%``
    unusable, which is the same class of defect one level up.
    """
    source = os.environ if environ is None else environ
    candidates = [
        Path(tempfile.gettempdir()),
        Path(source.get("ProgramData", r"C:\ProgramData")),
        Path(source.get("SystemDrive", "C:") + os.sep),
    ]
    return tuple(candidate for candidate in candidates if str(candidate).isascii())


def install_ascii_ca_bundle(
    bundle: str | os.PathLike[str] | None,
    *,
    environ: MutableMapping[str, str] | None = None,
    target_root: Path | None = None,
) -> str | None:
    """Point the CA environment variables at an ASCII copy of ``bundle``.

    Returns the path that should be used, or ``None`` when nothing had to change
    (an ASCII bundle, or a bundle that cannot be bridged). Setting the variables
    is the point: ``curl_cffi`` reads them for every session it creates, so one
    call at process entry fixes requests made through any module.
    """
    target_env = os.environ if environ is None else environ
    if bundle is None:
        return None
    source = Path(bundle)
    # An ASCII path needs no bridge, and a bundle that is not there cannot be
    # bridged: both leave the environment exactly as it was.
    if str(source).isascii() or not source.is_file():
        return None

    destination = _copy_to_ascii_root(source, target_root)
    if destination is None:
        return None
    for name in CA_ENV_VARS:
        # An operator-provided value that already works wins; the bridge only
        # fills in variables that are unset or point at an unusable path. An
        # unset variable is the normal case, and `""` is ASCII, so it must be
        # tested for emptiness first rather than by `isascii()` alone.
        current = str(target_env.get(name) or "")
        if not current or not current.isascii():
            target_env[name] = str(destination)
    return str(destination)


def _copy_to_ascii_root(source: Path, target_root: Path | None) -> Path | None:
    roots = (target_root,) if target_root is not None else ascii_candidate_roots()
    digest = _file_digest(source)
    if digest is None:
        return None
    filename = f"cacert-{digest[:16]}.pem"
    for root in roots:
        if root is None or not str(root).isascii():
            continue
        try:
            directory = root / CA_DIR_NAME
            directory.mkdir(parents=True, exist_ok=True)
            destination = directory / filename
            if destination.is_file() and destination.stat().st_size == source.stat().st_size:
                return destination
            # Copy beside the target and rename, so two processes racing at
            # startup cannot leave a half-written trust store behind.
            staging = directory / f"{filename}.{os.getpid()}.tmp"
            shutil.copyfile(source, staging)
            os.replace(staging, destination)
            return destination
        except OSError:
            continue
    return None


def _file_digest(source: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()
