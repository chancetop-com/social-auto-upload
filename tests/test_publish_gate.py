import argparse
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sau_cli
from sau_commands import arguments
from sau_commands.douyin import DouyinVideoUploadRequest, _build_video_uploader
from uploader.base_video import BaseVideoUploader
from uploader.publish_gate import remaining_seconds, wait_until_publish_allowed


class _FakeClock:
    def __init__(self, start: datetime) -> None:
        self.current = start

    def now(self, tz=None) -> datetime:  # mimics ``datetime.now(tz=...)``
        return self.current if tz is None else self.current.replace(tzinfo=tz)

    async def sleep(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


class _ListLogger:
    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def info(self, message: str) -> None:
        self.records.append(("info", message))

    def success(self, message: str) -> None:
        self.records.append(("success", message))


class PublishGateTests(unittest.TestCase):
    def test_none_target_returns_without_sleeping(self):
        clock = _FakeClock(datetime(2026, 1, 1, 12, 0, 0))
        asyncio.run(
            wait_until_publish_allowed(None, now=clock.now, sleep=clock.sleep)
        )
        self.assertEqual(clock.current, datetime(2026, 1, 1, 12, 0, 0))

    def test_past_target_returns_without_sleeping(self):
        start = datetime(2026, 1, 1, 12, 0, 0)
        clock = _FakeClock(start)
        asyncio.run(
            wait_until_publish_allowed(
                start - timedelta(minutes=1), now=clock.now, sleep=clock.sleep
            )
        )
        self.assertEqual(clock.current, start)

    def test_waits_until_target_and_logs(self):
        start = datetime(2026, 1, 1, 12, 0, 0)
        clock = _FakeClock(start)
        logger = _ListLogger()
        target = start + timedelta(seconds=12)

        asyncio.run(
            wait_until_publish_allowed(
                target,
                logger=logger,
                now=clock.now,
                sleep=clock.sleep,
                poll_seconds=5,
            )
        )

        self.assertGreaterEqual(clock.current, target)
        self.assertEqual(clock.current, target)
        self.assertEqual([level for level, _ in logger.records], ["info", "success"])

    def test_rejects_non_datetime_target(self):
        with self.assertRaises(TypeError):
            asyncio.run(wait_until_publish_allowed("2026-01-01 12:00"))

    def test_remaining_seconds_accepts_aware_target(self):
        target = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        now = datetime(2026, 1, 1, 11, 59, tzinfo=timezone.utc)
        self.assertEqual(remaining_seconds(target, now=lambda tz=None: now), 60)

    def test_base_uploader_defaults_to_no_gate(self):
        self.assertIsNone(BaseVideoUploader.publish_not_before)


class NotBeforeArgumentTests(unittest.TestCase):
    def test_parses_documented_format(self):
        self.assertEqual(
            arguments.not_before_value("2026-12-01 08:30"),
            datetime(2026, 12, 1, 8, 30),
        )

    def test_rejects_bad_format(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            arguments.not_before_value("2026/12/01 08:30")

    def test_past_times_are_allowed(self):
        value = datetime(2000, 1, 1, 0, 0)
        self.assertEqual(arguments.not_before_value(value.strftime("%Y-%m-%d %H:%M")), value)

    def test_every_upload_command_exposes_the_flag(self):
        parser = sau_cli.build_parser()
        upload_parsers = [
            candidate
            for candidate in self._iter_parsers(parser)
            if candidate.prog.rsplit(" ", 1)[-1].startswith("upload-")
        ]
        self.assertGreater(len(upload_parsers), 10)
        for candidate in upload_parsers:
            options = {
                option
                for action in candidate._actions
                for option in action.option_strings
            }
            self.assertIn("--not-before", options, candidate.prog)

    def test_upload_parser_reads_not_before(self):
        import tempfile

        parser = sau_cli.build_parser()
        with tempfile.NamedTemporaryFile(suffix=".mp4") as video:
            args = parser.parse_args(
                [
                    "douyin",
                    "upload-video",
                    "--file",
                    video.name,
                    "--title",
                    "hello",
                    "--not-before",
                    "2026-12-01 08:30",
                ]
            )
        self.assertEqual(args.not_before, datetime(2026, 12, 1, 8, 30))

    def test_request_value_reaches_uploader(self):
        target = datetime(2026, 12, 1, 8, 30)
        request = DouyinVideoUploadRequest(
            account_name="creator",
            video_file=Path("demo.mp4"),
            title="hello",
            description="",
            tags=[],
            publish_date=0,
            publish_not_before=target,
        )
        app = _build_video_uploader(request, "cookies/douyin_creator.json")
        self.assertEqual(app.publish_not_before, target)

    @staticmethod
    def _iter_parsers(parser):
        yield parser
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for sub_parser in action.choices.values():
                    yield from NotBeforeArgumentTests._iter_parsers(sub_parser)


if __name__ == "__main__":
    unittest.main()
