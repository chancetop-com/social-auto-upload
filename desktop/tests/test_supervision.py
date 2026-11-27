import os
from pathlib import Path
import subprocess
import sys
import time

import pytest


def wait_for(fn, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if value := fn():
            return value
        time.sleep(.04)
    pytest.fail(f"Timed out waiting for {fn}")


def test_restart_delays_reset_only_after_ten_stable_minutes():
    from sau_worker.supervisor import Backoff
    retry = Backoff()
    assert [retry.after_exit(1) for _ in range(10)] == [0, 10, 20, 40, 80, 160, 300, 300, 300, 300]
    assert retry.after_exit(599.99) == 300
    assert retry.after_exit(600) == 0
    assert retry.after_exit(0) == 10


@pytest.mark.skipif(os.name == "nt", reason="POSIX fixture sends SIGKILL to a disposable worker")
def test_busy_crash_keeps_child_occupied_and_force_targets_only_owned_children(tmp_path):
    from sau_worker.children import Children
    paired = tmp_path / "sau_cli.py"
    paired.write_text("import time, os\nfrom pathlib import Path\n"
                      "Path(os.environ['MARK']).write_text(str(os.getpid()))\ntime.sleep(45)\n")
    package = Path(__file__).resolve().parents[2] / "cli-service"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(map(str, (tmp_path, package)))}
    workers = []
    try:
        for name in ("our root", "other root"):
            state = tmp_path / name
            state.mkdir()
            marked = state / "observed"
            parent = subprocess.Popen([sys.executable, "-c",
                "import os,sys; from pathlib import Path; from sau_worker.children import Children\n"
                "with Children(Path(sys.argv[1])).launch('session-a', (sys.executable,), ['publish'], os.environ) as p:\n"
                "    p.communicate(timeout=60)",
                state], cwd=tmp_path, env={**env, "MARK": str(marked)})
            workers.append(parent)
            wait_for(marked.exists)
            parent.kill()
            parent.wait(3)
            assert Children(state).count(excluding="session-b") == 1
        registry = Children(tmp_path / "our root")
        registry.terminate()
        wait_for(lambda: registry.count() == 0)
        assert Children(tmp_path / "other root").count() == 1
    finally:
        for process in workers:
            if process.poll() is None:
                process.kill()
            process.wait()
        for name in ("our root", "other root"):
            registry = Children(tmp_path / name)
            registry.terminate()
            wait_for(lambda: registry.count() == 0)


def test_busy_windows_marker_cannot_discard_a_completed_cli_result(tmp_path, monkeypatch):
    from sau_worker.children import Children
    (tmp_path / "sau_cli.py").write_text("print('confirmed')\n")
    package = Path(__file__).resolve().parents[2] / "cli-service"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(map(str, (tmp_path, package)))}
    children = Children(tmp_path)
    unlink = Path.unlink
    def briefly_open(path, *args, **kwargs):
        if path.suffix == ".lock":
            raise PermissionError("fixture status reader holds the handle")
        return unlink(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", briefly_open)
        with children.launch("session", (sys.executable, "-P"), ["publish"], env) as process:
            output, _ = process.communicate(timeout=3)
    assert output.strip() == "confirmed" and process.returncode == 0
    assert children.count() == 0
