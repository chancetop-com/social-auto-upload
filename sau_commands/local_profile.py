"""CLI adapter for explicit local Profile reset; never starts a browser."""
from sau_commands.browser import managed_enabled
from utils.errors import UsageError
from utils.local_profile import reset_local_profile


def add_reset_profile_action(actions):
    parser = actions.add_parser("reset-profile", help="清空明确指定的本地浏览器 Profile")
    parser.add_argument("--account", required=True, help="原始账号别名")
    parser.add_argument("--browser-kind", required=True, choices=("chrome", "chromium"))


def run_reset_profile(args):
    if managed_enabled():
        raise UsageError("reset-profile 仅支持本地模式；请移除托管浏览器凭据后重试。")
    path = reset_local_profile(args.platform, args.account, args.browser_kind)
    print(f"Profile 已清空（不存在的目标视为已清空）: {path}")
    print(f"请先运行 sau {args.platform} login --account {args.account!r}；不要因此重新提交旧发布任务。")
    return 0
