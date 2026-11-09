# -*- coding: utf-8 -*-
"""Structural contract for managed browser providers.

This is a leaf module: it only imports ``typing`` so uploaders and the session
layer can refer to the provider type without pulling in any HTTP client or
desktop-app dependency.  Providers satisfy the protocol structurally; there is
deliberately no ABC and no ``@runtime_checkable``.
"""

from __future__ import annotations

from typing import Literal, Protocol

ProviderMode = Literal["multilogin", "adspower"]


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


__all__ = ["ManagedBrowserProvider", "ProviderMode"]
