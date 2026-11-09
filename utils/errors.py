# -*- coding: utf-8 -*-
"""Leaf error types shared by uploaders and the CLI.

No imports on purpose: uploaders may import this module without pulling in the
CLI, HTTP client, or any browser dependency.
"""

from __future__ import annotations


class LoginRequiredError(Exception):
    """Platform login state is invalid; the CLI maps this to exit code 10."""


class PublishResultUnknownError(Exception):
    """The publish click was sent but success was never observed.

    The post may already exist.  The CLI maps this to exit code 9 and callers
    must never retry automatically.
    """


class UsageError(Exception):
    """Invalid CLI usage discovered at runtime; the CLI maps this to exit code 2."""


class RateLimitedError(RuntimeError):
    """The local desktop API returned HTTP 429; the CLI maps this to exit code 11.

    Client layers never retry or sleep on this error.  It subclasses
    :class:`RuntimeError` so generic runtime failure handling remains valid,
    while ``sau_cli`` can catch it first to return the dedicated exit code.
    """


class StartIncompleteError(RuntimeError):
    """A managed profile was started but the start response was unusable.

    Internal lifecycle signal only: the session layer performs a best-effort
    stop and re-raises; the CLI treats it as an ordinary runtime failure.
    """
