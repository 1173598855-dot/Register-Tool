"""Stable browser-session factory; implementation lives behind this import path."""

from collections.abc import Callable
from typing import Any, Mapping

from ...kernel.driver_env import driver_config as _driver_config
from ..base import BROWSER_REGISTRATION_DRIVERS, BrowserRegistrationError, normalize_registration_driver
from ..browser_session import PlaywrightBrowserSession
from .managed import (
    CamoufoxBrowserSession,
    CloakBrowserSession,
    RoxyBrowserSession,
    # Bound in this module's namespace on purpose, none of it read here:
    # * `curl_requests` / `time` are patch seams -- tests patch
    #   `external_sessions.curl_requests.request` and `external_sessions.time.sleep`;
    # * `MOZ_DISABLE_CONTENT_SANDBOX` is read by tests/registration/test_camoufox_sandbox.py
    #   off this path.
    MOZ_DISABLE_CONTENT_SANDBOX,  # noqa: F401 - read by tests via this path
    curl_requests,  # noqa: F401 - patch seam
    time,  # noqa: F401 - patch seam
)
from .profiles import _inject_browser_profile, _inject_screen_size
from .probe import verify_browser_proxy_country

_BROWSER_SESSION_FACTORIES: dict[str, Callable[..., PlaywrightBrowserSession]] = {
    "cloak": CloakBrowserSession,
    "camoufox": CamoufoxBrowserSession,
    "roxy": RoxyBrowserSession,
}
assert set(_BROWSER_SESSION_FACTORIES) == BROWSER_REGISTRATION_DRIVERS - {"playwright"}


def create_browser_session(
    driver: str,
    *,
    config: Mapping[str, Any],
    proxy: str | None,
    headless: bool,
    timeout_ms: int,
    locale: str,
    timezone_id: str,
    browser_identity: Mapping[str, Any] | None = None,
    viewport: tuple[int, int] | None = None,
) -> PlaywrightBrowserSession:
    try:
        driver = normalize_registration_driver(driver)
    except ValueError as exc:
        raise BrowserRegistrationError("unsupported_registration_driver") from exc
    if driver == "protocol":
        raise BrowserRegistrationError("unsupported_registration_driver", "protocol")
    config = _inject_browser_profile(config, driver, browser_identity)
    # P1-3: let the pooled screen size reach Camoufox (it used to be pinned to a
    # hardcoded 1280x900). Playwright consumes the same value as its viewport
    # below; provider-owned drivers get None and are left untouched.
    config = _inject_screen_size(config, driver, viewport)
    kwargs = {
        "proxy": proxy,
        "headless": headless,
        "timeout_ms": timeout_ms,
        "locale": locale,
        "timezone_id": timezone_id,
    }
    if driver == "playwright":
        kwargs["viewport"] = viewport
        profile = str(_driver_config(config, "playwright").get("user_data_dir") or "").strip()
        if profile:
            kwargs["user_data_dir"] = profile
        return PlaywrightBrowserSession(**kwargs)
    factory = _BROWSER_SESSION_FACTORIES.get(driver)
    if factory is None:
        raise BrowserRegistrationError("unsupported_registration_driver", driver)
    return factory(config=config, **kwargs)


__all__ = [
    "CamoufoxBrowserSession",
    "CloakBrowserSession",
    "RoxyBrowserSession",
    "create_browser_session",
    "verify_browser_proxy_country",
]
