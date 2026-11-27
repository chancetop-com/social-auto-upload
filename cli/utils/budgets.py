import math
import os

from utils.errors import UsageError


def seconds(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, default))
        if not math.isfinite(value) or value <= 0:
            raise ValueError
        return value
    except ValueError:
        raise UsageError(f"{name} must be a positive finite number of seconds") from None
