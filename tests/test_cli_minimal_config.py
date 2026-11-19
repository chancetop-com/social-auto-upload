"""The installed public CLI accepts existing configurations with optional fields absent."""
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class MinimalConfigurationCliTests(unittest.TestCase):
    def test_help_starts_with_only_base_dir_and_without_browser_installation(self):
        with tempfile.TemporaryDirectory() as root:
            script = """
import sys, types
from pathlib import Path
conf = types.ModuleType('conf')
conf.BASE_DIR = Path(sys.argv[1])
sys.modules['conf'] = conf
from sau_cli import main
raise SystemExit(main(['--help']))
"""
            result = subprocess.run(
                [sys.executable, '-c', script, root],
                cwd=Path(__file__).resolve().parents[1],
                env={**os.environ, 'PLAYWRIGHT_BROWSERS_PATH': str(Path(root) / 'absent')},
                text=True, capture_output=True, timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        choices = re.search(r'\{([^}]+)\}', result.stdout)
        self.assertIsNotNone(choices, result.stdout)
        self.assertEqual(set(choices.group(1).split(',')), {
            'article', 'facebook', 'facebook-page', 'instagram', 'media', 'rednote',
            'tiktok', 'xiaohongshu', 'youtube',
        })

    def test_retired_platforms_fail_during_argument_parsing_in_every_mode(self):
        from contextlib import redirect_stderr
        from io import StringIO
        from unittest.mock import AsyncMock, patch

        from sau_cli import main

        retired = (
            'douyin', 'kuaishou', 'bilibili', 'tencent', 'dayu', 'baijiahao',
            'alipay', 'weibo', 'hupu', 'xueqiu', 'zhihu',
        )
        for credentials in ({}, {'MLX_API_TOKEN': 'test'}, {'ADSPOWER_API_KEY': 'test'}):
            with patch.dict(os.environ, credentials, clear=True):
                for platform in retired:
                    with self.subTest(platform=platform, provider=list(credentials)):
                        error = StringIO()
                        with patch('sau_cli.dispatch', new_callable=AsyncMock) as dispatch:
                            with redirect_stderr(error), self.assertRaises(SystemExit) as caught:
                                main([platform, 'check', '--account', 'existing'])
                            dispatch.assert_not_called()
                        self.assertEqual(caught.exception.code, 2)
                        self.assertIn(f"invalid choice: '{platform}'", error.getvalue())
