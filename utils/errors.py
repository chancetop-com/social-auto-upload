# -*- coding: utf-8 -*-
"""Leaf error types shared by uploaders and the CLI.

No imports on purpose: uploaders may import this module without pulling in the
CLI, HTTP client, or any browser dependency.
"""

from __future__ import annotations


class LoginRequiredError(Exception):
    """Platform login state is invalid; the CLI maps this to exit code 10.

    ``reason`` is ``"login"`` or ``"verification"``; ``publish_attempted`` says
    whether the publish click had already been dispatched (exit 10 must never
    claim "not published" after a dispatch).  Both default to the pre-dispatch
    login case so legacy ``LoginRequiredError(message)`` keeps working.
    """

    def __init__(
        self,
        message: str = "",
        *,
        reason: str = "login",
        publish_attempted: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.publish_attempted = bool(publish_attempted)


class PageCheckError(RuntimeError):
    """An explicit HTTP/page check failed before submission (CLI exit 1).

    Authentication diagnostics must not replace this already classified fault.
    """


class PublishResultUnknownError(Exception):
    """The publish click was sent but success was never observed.

    The post may already exist.  The CLI maps this to exit code 9 and callers
    must never retry automatically.
    """


class UsageError(Exception):
    """Invalid CLI usage discovered at runtime; the CLI maps this to exit code 2."""


class LocationVerificationError(RuntimeError):
    """Pre-publish location failure carrying the same fields as the CLI line.

    Kept in this dependency-free module because both uploaders raise it and the
    CLI reports the same fields after catching an ordinary runtime failure.
    """

    def __init__(
        self,
        *,
        requested: str,
        reason: str,
        clicked_name: str | None = None,
        address: str | None = None,
        final_name: str | None = None,
    ) -> None:
        self.requested = requested
        self.reason = reason
        self.clicked_name = clicked_name
        self.address = address
        self.final_name = final_name
        if clicked_name is None:
            clicked = "未点选"
        else:
            shown = (clicked_name or "").strip()
            address_text = (address or "").strip()
            clicked = f"{shown} · {address_text}" if address_text else shown
        if final_name is None:
            final = "未读到"
        elif not final_name:
            final = "（空）"
        else:
            final = final_name
        super().__init__(
            f"帖子地点设置失败：请求={requested}，所点行={clicked}，"
            f"终值={final}，原因={reason}；尚未点击发布。"
        )


class RateLimitedError(RuntimeError):
    """The local desktop API returned HTTP 429; the CLI maps this to exit code 11.

    Client layers never retry or sleep on this error.  It subclasses
    :class:`RuntimeError` so generic runtime failure handling remains valid,
    while ``sau_cli`` can catch it first to return the dedicated exit code.
    """


class ProviderRequestRejected(RuntimeError):
    """The provider explicitly refused the request before performing it."""


class ProfileStartingError(RuntimeError):
    """The provider identifies an unfinished startup phase."""


class ProfileConnectionUnavailableError(RuntimeError):
    """The provider cannot supply a usable connection to the current run."""


class StartIncompleteError(RuntimeError):
    """A managed profile was started but the start response was unusable.

    Internal lifecycle signal only: the session layer performs a best-effort
    stop and re-raises; the CLI treats it as an ordinary runtime failure.
    """
