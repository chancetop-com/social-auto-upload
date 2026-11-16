"""Best-effort local-session teardown, separate from the publication outcome."""

from loguru import logger


async def close_browser_resources(*, context=None, browser=None) -> None:
    """Close each owned resource even if the preceding close fails.

    Ordinary cleanup failures must not replace success or the original publish
    exception. Cancellation is deliberately not swallowed.
    """
    try:
        if context is not None:
            try:
                await context.close()
            except Exception as error:  # noqa: BLE001 - cleanup must preserve the primary outcome
                logger.warning(
                    "Browser context cleanup failed; preserving upload result: {}",
                    error,
                )
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception as error:  # noqa: BLE001 - cleanup must preserve the primary outcome
                logger.warning(
                    "Browser cleanup failed; preserving upload result: {}", error
                )


async def save_upload_session(context, account_file) -> bool:
    """Refresh cookies after a completed upload without making it retryable.

    Login must still require successful persistence; this helper is only for
    post-upload write-back.
    """
    try:
        await context.storage_state(path=account_file)
    except Exception as error:  # noqa: BLE001 - cleanup must preserve the primary outcome
        logger.warning("Cookie write-back failed; preserving upload result: {}", error)
        return False
    return True
