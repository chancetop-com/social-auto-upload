"""Exercise manual login through a real terminal without a browser or account."""
import os
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


LOGIN_RUNNER = r'''
import os
import sys
from pathlib import Path
from unittest.mock import patch
import conf
import sau_cli
from sau_commands import tiktok
from tests.fakes import FakePlaywright
from tests.test_mlx_tiktok import _AsyncCM
from tests.test_tiktok_profile_cli import ProbeContext

pw = FakePlaywright()
context = ProbeContext()
pw.chromium.persistent_context = context
with patch.object(conf, "BASE_DIR", Path(sys.argv[1])), \
     patch.object(conf, "LOCAL_CHROME_PATH", ""), \
     patch.object(conf, "LOCAL_CHROME_HEADLESS", True), \
     patch.dict(os.environ, {"MLX_API_TOKEN": "", "ADSPOWER_API_KEY": ""}), \
     patch.object(tiktok, "async_playwright", lambda: _AsyncCM(pw)):
    try:
        result = sau_cli.main(["tiktok", "login", "--account", "terminal-test"])
    except KeyboardInterrupt:
        result = 130
    print(f"CONTEXT_CLOSED={context.closed}", flush=True)
    raise SystemExit(result)
'''


@unittest.skipIf(os.name == 'nt', 'POSIX PTY integration test')
class TikTokLoginTerminalTests(unittest.TestCase):
    def run_terminal(self, action):
        import pty

        master, slave = pty.openpty()
        output = b''
        with tempfile.TemporaryDirectory() as root:
            process = subprocess.Popen(
                [sys.executable, '-c', LOGIN_RUNNER, root],
                cwd=Path(__file__).resolve().parents[1],
                stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            os.close(slave)
            try:
                deadline = time.monotonic() + 5
                while '回到终端按 Enter'.encode() not in output:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not select.select([process.stdout], [], [], remaining)[0]:
                        self.fail(f'login prompt not shown: {output.decode(errors="replace")}')
                    data = os.read(process.stdout.fileno(), 65536)
                    if not data:
                        self.fail(f'login exited before its prompt: {output.decode(errors="replace")}')
                    output += data
                # The prompt precedes the input wait. Leave the terminal empty
                # long enough to verify it remains interactive before acting.
                time.sleep(0.1)
                self.assertIsNone(process.poll(), output.decode(errors='replace'))
                action(process, master)
                try:
                    remaining_output, _ = process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    self.fail('login did not exit after terminal input/cancellation')
                output += remaining_output
                self.assertIn(b'CONTEXT_CLOSED=True', output)
                return process.returncode, output.decode(errors='replace')
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=2)
                process.stdout.close()
                os.close(master)

    def test_ctrl_c_finishes_process_while_waiting_for_enter(self):
        code, output = self.run_terminal(lambda process, terminal: process.send_signal(signal.SIGINT))
        self.assertEqual(code, 130, output)

    def test_enter_checks_login_and_finishes_normally(self):
        code, output = self.run_terminal(lambda process, terminal: os.write(terminal, b'\n'))
        self.assertEqual(code, 0, output)
        self.assertIn('TikTok login flow completed: terminal-test', output)

    def test_end_of_input_cancels_login_and_finishes(self):
        code, output = self.run_terminal(lambda process, terminal: os.write(terminal, b'\x04'))
        self.assertEqual(code, 1, output)
        self.assertIn('无法读取终端输入', output)
