# -*- coding: utf-8 -*-
"""TikTok first-run overlays that intercept upload-form clicks.

Offline only: the helpers are driven with in-memory locator fakes.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from uploader.tk_uploader.main_chrome import TiktokBaseUploader
from uploader.tk_uploader.tk_config import TIKTOK_OVERLAY_CLICK_TIMEOUT_MS


def _locator(count: int = 0) -> MagicMock:
    locator = MagicMock()
    locator.count = AsyncMock(return_value=count)
    locator.first = locator
    locator.filter.return_value = locator
    locator.click = AsyncMock()
    locator.wait_for = AsyncMock()
    return locator


class DismissOverlayTests(unittest.TestCase):
    def test_cancel_dismisses_automatic_content_checks_modal(self):
        dialog = _locator(1)
        cancel = _locator(1)
        missing = _locator(0)
        dialog.get_by_role = MagicMock(
            side_effect=lambda role, name: cancel if name == "Cancel" else missing
        )
        dialog_root = MagicMock()
        dialog_root.filter.return_value = dialog
        joyride = _locator(0)
        page = MagicMock()
        page.locator = MagicMock(
            side_effect=lambda selector: (
                dialog_root
                if selector == '[role="dialog"]'
                else joyride
            )
        )

        asyncio.run(TiktokBaseUploader().dismiss_blocking_overlays(page))

        cancel.click.assert_awaited_once_with(
            timeout=TIKTOK_OVERLAY_CLICK_TIMEOUT_MS
        )
        dialog.wait_for.assert_awaited_once()

    def test_joyride_overlay_is_clicked_away(self):
        dialog = _locator(0)
        dialog_root = MagicMock()
        dialog_root.filter.return_value = dialog
        joyride = _locator(1)
        overlay = _locator(1)
        page = MagicMock()
        page.locator = MagicMock(
            side_effect=lambda selector: {
                '[role="dialog"]': dialog_root,
                "#react-joyride-portal": joyride,
                ".react-joyride__overlay": overlay,
            }[selector]
        )

        asyncio.run(TiktokBaseUploader().dismiss_blocking_overlays(page))

        overlay.click.assert_awaited_once_with(
            timeout=TIKTOK_OVERLAY_CLICK_TIMEOUT_MS
        )
        joyride.wait_for.assert_awaited_once()

    def test_no_overlays_is_a_noop(self):
        dialog = _locator(0)
        dialog_root = MagicMock()
        dialog_root.filter.return_value = dialog
        joyride = _locator(0)
        page = MagicMock()
        page.locator = MagicMock(
            side_effect=lambda selector: (
                dialog_root
                if selector == '[role="dialog"]'
                else joyride
            )
        )

        asyncio.run(TiktokBaseUploader().dismiss_blocking_overlays(page))

        dialog.get_by_role.assert_not_called()
        joyride.first.click.assert_not_awaited()



def setUpModule():
    """Legacy TikTok fakes model the pre-humanize DOM seam.

    ``HUMANIZE=0`` is the semantic switch for exactly this: one ``insert_text``
    per text field and one ``locator.click`` per click.  The humanized
    behaviour itself is covered by ``tests/test_tiktok_humanize.py``.
    """
    import os

    os.environ["HUMANIZE"] = "0"


def tearDownModule():
    import os

    os.environ.pop("HUMANIZE", None)

if __name__ == "__main__":
    unittest.main()
