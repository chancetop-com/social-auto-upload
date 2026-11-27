# -*- coding: utf-8 -*-
"""Compatibility shim for the former Multilogin-only CLI helpers.

The canonical implementation lives in :mod:`sau_commands.browser`.  All old
symbols remain importable here with their historical MLX-only semantics; new
provider-aware names are re-exported for callers migrating off the shim.
"""

from __future__ import annotations

from sau_commands.browser import (
    add_browser_flags,
    add_multilogin_flags,
    identity_unverified_format,
    login_required_error,
    managed_app_label,
    managed_enabled,
    managed_timezone_hint,
    multilogin_enabled,
    reject_managed_login,
    reject_managed_platform,
    reject_multilogin_login,
    reject_multilogin_platform,
    require_account,
    require_local_account,
    resolve_account_label,
    resolve_managed_provider,
    resolve_multilogin_target,
)

__all__ = [
    "add_browser_flags",
    "add_multilogin_flags",
    "identity_unverified_format",
    "login_required_error",
    "managed_app_label",
    "managed_enabled",
    "managed_timezone_hint",
    "multilogin_enabled",
    "reject_managed_login",
    "reject_managed_platform",
    "reject_multilogin_login",
    "reject_multilogin_platform",
    "require_account",
    "require_local_account",
    "resolve_account_label",
    "resolve_managed_provider",
    "resolve_multilogin_target",
]
