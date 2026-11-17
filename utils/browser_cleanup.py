"""Best-effort teardown, separate from login and publication outcomes."""

from loguru import logger


async def _close_resource(resource, label: str) -> None:
    if resource is None:
        return
    try:
        await resource.close()
    except Exception as error:  # noqa: BLE001 - preserve the primary outcome
        logger.warning("{} cleanup failed; preserving operation result: {}", label, error)


async def close_browser_resources(*, page=None, context=None, browser=None) -> None:
    """Close each owned resource even if the preceding close fails.

    Ordinary cleanup failures must not replace success or the original operation
    exception. Cancellation is deliberately not swallowed.
    """
    try:
        await _close_resource(page, "Page")
    finally:
        try:
            await _close_resource(context, "Browser context")
        finally:
            await _close_resource(browser, "Browser")
