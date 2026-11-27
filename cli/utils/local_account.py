"""Name-only compatibility for direct local uploader calls."""
from pathlib import Path

from utils.errors import UsageError


def local_account_alias(account_file=None, account_name=None, *, platform,
                        allow_unprefixed_json=False,
                        missing_message="本地调用需要 account_name 账号别名。"):
    """Keep explicit aliases raw; translate legacy JSON names without file I/O.

    TikTok, Rednote and Xiaohongshu also accept unprefixed JSON filenames.
    Other callers preserve strings that do not match their platform prefix.
    """
    if account_name is not None:
        return account_name
    if account_file is None:
        raise UsageError(missing_message)
    name = Path(str(account_file)).name
    prefix = f"{platform}_"
    if name.endswith(".json") and (allow_unprefixed_json or name.startswith(prefix)):
        return name[:-5].removeprefix(prefix)
    return str(account_file)
