"""Click a captured topic node without retrying a possibly dispatched click."""

from utils.dom import ElementUnusableError, is_interactive_element_handle
from utils.humanize import Humanizer, maybe_dispatched


async def click_topic_candidate(candidate, humanizer: Humanizer, *, rescan_moved: bool = False) -> bool:
    """Rescan a detached snapshot, or an explicitly allowed, still usable moved row.

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
        if await candidate.evaluate("el => el.isConnected") is False:
            return False
        if rescan_moved and error.reason == "point-drift":
            if await is_interactive_element_handle(candidate):
                return False
        raise
    return True
