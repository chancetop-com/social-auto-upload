# -*- coding: utf-8 -*-
"""Name comparison shared by post-location and caption readback.

Platforms render the same name with different spacing (for example a candidate
row with a line break versus the collapsed control).  Matching therefore trims
the ends, collapses every whitespace run to one space and casefolds; displayed
values keep their original form.
"""

from __future__ import annotations

from typing import Any


def normalize_text(value: Any) -> str:
    """Trim, collapse whitespace and casefold; ``None`` becomes ``""``."""
    if value is None:
        return ""
    return " ".join(str(value).split()).casefold()
