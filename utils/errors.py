# -*- coding: utf-8 -*-
"""Leaf error types shared by uploaders and the CLI.

No imports on purpose: uploaders may import this module without pulling in the
CLI, HTTP client, or any browser dependency.
"""

from __future__ import annotations


class LoginRequiredError(Exception):
    """Platform login state is invalid; the CLI maps this to exit code 10."""


class UsageError(Exception):
    """Invalid CLI usage discovered at runtime; the CLI maps this to exit code 2."""
