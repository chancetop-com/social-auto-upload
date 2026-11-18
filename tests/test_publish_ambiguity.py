"""An ambiguous publish control is terminal, even if the next poll would be ready."""

import unittest
from unittest.mock import AsyncMock, patch

from uploader.publish_timeout import PublishTimeoutBudget
from uploader.rednote_uploader import main as rednote
from uploader.xiaohongshu_uploader import main as xhs
from utils.dom import ElementUnusableError


class PublishAmbiguityTests(unittest.IsolatedAsyncioTestCase):
    async def test_ambiguity_stops_both_waiting_gates_on_the_first_probe(self):
        for module in (rednote, xhs):
            for name in ("_wait_for_arm", "_video_upload_gate"):
                with self.subTest(platform=module.__name__, gate=name):
                    ready = AsyncMock(
                        side_effect=[(False, "ambiguous:2"), (True, None)]
                    )
                    with (
                        patch.object(module, "_arm_ready", ready),
                        patch.object(module, "_check_blocked", AsyncMock()),
                        patch.object(
                            module,
                            "_video_upload_failure",
                            AsyncMock(return_value=None),
                        ),
                        patch.object(module.asyncio, "sleep", AsyncMock()) as sleep,
                    ):
                        kwargs = {
                            "budget": PublishTimeoutBudget("fixture"),
                            "mode": "local",
                        }
                        if name == "_wait_for_arm":
                            kwargs["publish_clicked"] = False
                        with self.assertRaises(ElementUnusableError) as caught:
                            await getattr(module, name)(object(), **kwargs)
                        self.assertEqual(caught.exception.reason, "ambiguous:2")
                        self.assertFalse(caught.exception.publish_clicked)
                        ready.assert_awaited_once()
                        sleep.assert_not_awaited()

    async def test_arm_counts_duplicates_before_any_scroll_or_geometry_wait(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        for module in (rednote, xhs):
            with self.subTest(platform=module.__name__):
                locator = SimpleNamespace(count=AsyncMock(return_value=2))
                page = SimpleNamespace(locator=Mock(return_value=locator))
                with patch.object(module, "ensure_in_viewport", AsyncMock()) as scroll:
                    result = await module._arm_ready(
                        page, budget=PublishTimeoutBudget("fixture")
                    )
                self.assertEqual(result, (False, "ambiguous:2"))
                scroll.assert_not_awaited()


class AmbiguousLocator:
    """Two enabled buttons; selecting .first would hide the ambiguity."""

    def __init__(self, count=2):
        self.matches = count
        self.count_calls = 0

    async def count(self):
        self.count_calls += 1
        return self.matches

    @property
    def first(self):
        return AmbiguousLocator(1)

    @property
    def last(self):
        return self.first

    def nth(self, _index):
        return self.first

    async def is_visible(self):
        return True

    async def is_enabled(self):
        return True

    async def is_disabled(self):
        return False

    async def get_attribute(self, _name):
        return None

    async def wait_for(self, **_kwargs):
        pass

    async def scroll_into_view_if_needed(self):
        pass


class OtherPlatformAmbiguityTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_publish_buttons_never_pass_media_or_publish_gates(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        from uploader.tk_uploader import main_chrome as tiktok

        cases = (
            (tiktok.TiktokVideo, "wait_media_ready"),
            (tiktok.TiktokNote, "wait_media_ready"),
            (tiktok.TiktokVideo, "wait_publish_ready"),
        )
        for cls, method in cases:
            with self.subTest(uploader=cls.__name__, gate=method):
                duplicate = AmbiguousLocator()
                page = SimpleNamespace(
                    locator=Mock(return_value=duplicate),
                    get_by_role=Mock(return_value=duplicate),
                    get_by_text=Mock(return_value=duplicate),
                    evaluate=AsyncMock(),
                    wait_for_timeout=AsyncMock(),
                    url="/post/create",
                )
                # An authenticated Studio page with duplicate publish
                # controls, not duplicate login forms or login text.
                absent = AmbiguousLocator(0)
                page.locator = Mock(
                    side_effect=lambda selector: (
                        duplicate
                        if selector in (
                            '[data-e2e="post_video_button"]',
                            "div.button-group button",
                        )
                        else absent
                    )
                )
                page.get_by_text = Mock(return_value=absent)
                app = cls.__new__(cls)
                app.locator_base = page
                app._publish_budget = PublishTimeoutBudget("fixture")
                humanizer = SimpleNamespace(
                    before_submit=AsyncMock(),
                    press=AsyncMock(),
                    click=AsyncMock(
                        side_effect=AssertionError("must not click ambiguous button")
                    ),
                )
                app._humanizer = Mock(return_value=humanizer)
                app._dismiss_switch_account_dialog = AsyncMock()
                with (
                    patch.object(
                        tiktok.asyncio,
                        "sleep",
                        AsyncMock(
                            side_effect=AssertionError("must not retry ambiguity")
                        ),
                    ),
                    self.assertRaises(ElementUnusableError) as caught,
                ):
                    await getattr(app, method)(page)
                self.assertEqual(caught.exception.reason, "ambiguous:2")
                humanizer.click.assert_not_awaited()

    async def test_instagram_stops_instead_of_waiting_for_duplicate_to_disappear(self):
        from uploader.meta_uploader.insgraph_uploader import main as instagram

        app = instagram.InstagramUploader.__new__(instagram.InstagramUploader)
        locator = AmbiguousLocator()
        # Old expect(count=1) silently waited; emulate its eventual success.
        from types import SimpleNamespace

        expectation = SimpleNamespace(
            to_have_count=AsyncMock(), to_be_enabled=AsyncMock()
        )
        with (
            patch.object(instagram, "expect", return_value=expectation),
            patch.object(
                instagram.asyncio,
                "sleep",
                AsyncMock(side_effect=AssertionError("must not retry ambiguity")),
            ),
            self.assertRaises(ElementUnusableError) as caught,
        ):
            await app._wait_until_publish_ready(
                locator, budget=PublishTimeoutBudget("fixture")
            )
        self.assertEqual(caught.exception.reason, "ambiguous:2")

    async def test_youtube_publish_helper_rejects_duplicates(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        from uploader.youtube_uploader import main as youtube

        page = SimpleNamespace(locator=Mock(return_value=AmbiguousLocator()))
        humanizer = SimpleNamespace(click=AsyncMock())
        with self.assertRaises(ElementUnusableError):
            await youtube._click_if_present(
                page, "#done-button", humanizer=humanizer, unique=True
            )
        humanizer.click.assert_not_awaited()


    async def test_tiktok_confirmation_rejects_duplicate_buttons_before_click(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        from uploader.tk_uploader import main_chrome as tiktok

        class Dialog(AmbiguousLocator):
            def nth(self, _index):
                return self

            def get_by_role(self, *_args, **_kwargs):
                return AmbiguousLocator()

        page = SimpleNamespace(locator=Mock(return_value=Dialog(1)))
        app = tiktok.TiktokVideo.__new__(tiktok.TiktokVideo)
        app.publish_date = 0
        humanizer = SimpleNamespace(click=AsyncMock())
        app._humanizer = Mock(return_value=humanizer)
        with self.assertRaises(ElementUnusableError):
            await app._click_post_now(page)
        humanizer.click.assert_not_awaited()
