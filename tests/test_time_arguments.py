"""CLI 时间参数的格式契约。"""
import tempfile
import unittest
from datetime import datetime, timezone

import sau_cli
from sau_commands import arguments


class ScheduleArgumentTests(unittest.TestCase):
    def test_parses_utc_iso_with_z(self):
        self.assertEqual(
            arguments.parse_schedule("2026-11-12T10:30:00Z"),
            datetime(2026, 11, 12, 10, 30, tzinfo=timezone.utc),
        )

    def test_rejects_naive_schedule(self):
        for raw in ("2026-11-12 10:30", "2026-11-12T10:30:00"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                arguments.parse_schedule(raw)

    def test_rejects_non_utc_offset(self):
        with self.assertRaises(ValueError):
            arguments.parse_schedule("2026-11-12T18:30:00+08:00")

    def test_rejects_non_zero_seconds(self):
        with self.assertRaises(ValueError):
            arguments.parse_schedule("2026-11-12T10:30:45Z")

    def test_omitted_schedule_means_immediate(self):
        self.assertEqual(arguments.parse_schedule(None), 0)

    def test_empty_schedule_is_rejected(self):
        with self.assertRaises(ValueError):
            arguments.parse_schedule("")

    def test_upload_parser_reads_utc_schedule(self):
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
                    "--schedule",
                    "2026-11-12T10:30:00Z",
                ]
            )
        self.assertEqual(
            args.schedule,
            datetime(2026, 11, 12, 10, 30, tzinfo=timezone.utc),
        )

if __name__ == "__main__":
    unittest.main()
