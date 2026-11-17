"""The installed public CLI accepts existing configurations with optional fields absent."""
import os
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
        self.assertIn('tiktok', result.stdout)
        self.assertIn('xueqiu', result.stdout)
