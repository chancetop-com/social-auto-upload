"""Click a captured topic node without retrying a possibly dispatched click."""

from utils.dom import ElementUnusableError
from utils.humanize import Humanizer, maybe_dispatched


async def click_topic_candidate(candidate, humanizer: Humanizer) -> bool:
    """False means the snapshot detached before dispatch; the caller may rescan.

    Keep the platform's deadline and fallback outside this helper. A failed
    connection probe, ambiguity, occlusion, or possible dispatch must propagate.
    """
    if await candidate.evaluate("el => el.isConnected") is False:
        return False
    try:
        await humanizer.click(candidate)
    except ElementUnusableError as error:
        if maybe_dispatched(error) or error.reason not in {
            "not-attached", "no-bounding-box", "zero-box", "point-drift",
        }:
            raise
        if await candidate.evaluate("el => el.isConnected") is not False:
            raise
        return False
    return True
