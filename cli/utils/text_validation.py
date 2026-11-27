"""Input constraints that must be checked before browser interaction."""


def validate_single_line(text: str, *, label: str = "标题") -> str:
    """Reject keys that would leave a single-line field; preserve valid input."""
    if any(char in (text or "") for char in ("\n", "\r", "\t")):
        raise ValueError(f"{label}必须为单行文字，不能包含换行或制表符")
    return text
