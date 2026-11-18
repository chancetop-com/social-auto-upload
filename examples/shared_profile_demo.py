"""两个独立 CLI 进程共用一个托管 profile 的 macOS / Linux 示例。

在同一工作目录的两个终端分别运行：
    python3 examples/shared_profile_demo.py instagram --work-seconds 8
    python3 examples/shared_profile_demo.py tiktok --work-seconds 2

示例模拟 provider 和上传任务。shared_endpoint 里的进程锁是真实的。
"""

import argparse
import fcntl
import hashlib
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


@contextmanager
def lifecycle_lock(directory):
    with (directory / "lifecycle.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def no_active_users(lock):
    """在生命周期锁内探测使用者；独占锁成功说明此时没有共享锁。"""
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    fcntl.flock(lock, fcntl.LOCK_UN)
    return True


@contextmanager
def shared_endpoint(directory, *, start, stop):
    """directory 标识一个 provider 下的一个 profile。start/stop 由调用方提供。"""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    endpoint_file = directory / "endpoint"
    # 两个 .lock 文件永久保留，所有进程必须锁住同一个 inode。
    with (directory / "users.lock").open("a+b") as users:
        with lifecycle_lock(directory):
            if no_active_users(users):
                # 没有活跃使用者却有记录，说明上次 start/stop 或最后一个进程异常退出。
                if endpoint_file.exists():
                    raise RuntimeError(f"上次会话状态未确认，请先核对 provider。记录位于 {endpoint_file}")
                # 即便 start 在返回地址前中断，下一个进程也能发现这次未完成的启动。
                endpoint_file.touch(mode=0o600, exist_ok=False)
                endpoint = start()
                endpoint_file.write_text(endpoint, encoding="utf-8")
            else:
                endpoint = endpoint_file.read_text(encoding="utf-8")
            # 每条 CLI 在操作自己的标签页期间持有一个共享锁。
            fcntl.flock(users, fcntl.LOCK_SH)

        try:
            yield endpoint
        finally:
            with lifecycle_lock(directory):
                fcntl.flock(users, fcntl.LOCK_UN)
                if no_active_users(users):
                    stop()
                    endpoint_file.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", choices=("instagram", "tiktok"))
    parser.add_argument("--profile-id", default="demo")
    parser.add_argument("--state-dir", type=Path, default=Path(".local/shared-profile-demo"))
    parser.add_argument("--work-seconds", type=int, choices=range(1, 61), metavar="1..60", default=5)
    args = parser.parse_args()
    profile_key = hashlib.sha256(args.profile_id.encode()).hexdigest()

    def log(message):
        print(f"{args.platform}: {message}", flush=True)

    def start():
        log("START profile")
        return f"demo://{uuid4().hex}"

    def stop():
        log("STOP profile")

    with shared_endpoint(args.state_dir / profile_key, start=start, stop=stop) as endpoint:
        log(f"开始使用自己的标签页，连接地址 {endpoint}")
        time.sleep(args.work_seconds)
        log("完成自己的任务")


if __name__ == "__main__":
    main()
