# -*- coding: utf-8 -*-
"""Structural contract for managed browser providers.

This is a leaf module: it only imports ``typing`` so uploaders and the session
layer can refer to the provider type without pulling in any HTTP client or
desktop-app dependency.  Providers satisfy the protocol structurally; there is
deliberately no ABC and no ``@runtime_checkable``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

ProviderMode = Literal["multilogin", "adspower", "bitbrowser"]


@dataclass(frozen=True, slots=True)
class ProfileObservation:
    """Authenticated observation of the requested profile's current run."""

    active: bool
    endpoint: str | None = field(default=None, repr=False)
    headless: bool | None = None
    launched_at_ns: int | None = None


@dataclass(frozen=True, slots=True)
class ProviderHints:
    """Product-specific remediation for shared lifecycle diagnostics.

    The defaults are provider-neutral: they never name a desktop application.
    A provider may override only the fragments that are genuinely specific to
    its own stop/start/CDP behaviour.
    """

    stop_settle_hint: str = "请先关闭该 Profile 的浏览器窗口后重试。"
    stop_unconfirmed_hint: str = (
        "请检查该 Provider 的 Local API 与窗口状态后重试。"
    )
    # ``None`` keeps the provider's original start-uncertainty error.  A value
    # turns it into an actionable "start result unknown" diagnostic.
    start_unconfirmed_hint: str | None = None
    # Appended after "无法通过 CDP 连接当前 Profile。" when non-empty.
    cdp_connect_hint: str = ""


class ManagedBrowserProvider(Protocol):
    """A desktop-app profile that can be started, attached to, and stopped."""

    mode: ProviderMode
    profile_id: str

    def probe(self) -> None:
        """Verify the local desktop app / API is reachable."""

    def start(self, headless: bool) -> str:
        """Start the profile and return a URL accepted by ``connect_over_cdp``."""

    def stop(self) -> None:
        """Stop the profile owned by this session."""

    def status(self) -> str:
        """Return diagnostic profile state; never used for control flow."""


class SharedBrowserProvider(ManagedBrowserProvider, Protocol):
    # Some desktop APIs acknowledge Stop before the browser actually exits.
    asynchronous_stop: bool
    # Minimum quiet period after a stop acknowledgement before the next start.
    stop_settle_seconds: float
    # Product-specific wording for shared lifecycle diagnostics.
    hints: ProviderHints

    @property
    def resource_identity(self) -> str:
        """Canonical identity of the service or folder containing the profile."""

    def observe(self) -> ProfileObservation:
        """Report the current run, or raise when its identity/state is uncertain."""


__all__ = [
    "ManagedBrowserProvider",
    "ProfileObservation",
    "ProviderHints",
    "ProviderMode",
    "SharedBrowserProvider",
]
