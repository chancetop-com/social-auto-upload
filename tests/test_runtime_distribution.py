"""Installed package surface for the supported browser runtime."""

import importlib
import importlib.resources
import unittest


class RuntimeDistributionTests(unittest.TestCase):
    def test_distribution_omits_retired_browser_entries_and_stealth_resource(self):
        for package, resource in (
            ("uploader.tk_uploader", "main.py"),
            ("utils", "stealth.min.js"),
        ):
            with self.subTest(package=package, resource=resource):
                self.assertFalse(importlib.resources.files(package).joinpath(resource).is_file())

    def test_supported_tencent_video_remains_without_unfinished_note_export(self):
        tencent = importlib.import_module("uploader.tencent_uploader")
        self.assertTrue(callable(tencent.TencentVideo))
        self.assertFalse(hasattr(tencent, "TencentNote"))
        self.assertNotIn("TencentNote", tencent.__all__)

    def test_distribution_retains_formal_uploaders_and_article_resources(self):
        for package, resource in (
            ("uploader.tk_uploader", "main_chrome.py"),
            ("uploader.tencent_uploader", "main.py"),
            ("uploader.bilibili_uploader", "runtime.py"),
            ("utils", "article_renderer/render.mjs"),
            ("utils", "article_renderer/package.json"),
            ("utils", "article_renderer/NOTICE.md"),
        ):
            with self.subTest(package=package, resource=resource):
                self.assertTrue(importlib.resources.files(package).joinpath(resource).is_file())
