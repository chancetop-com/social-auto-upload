"""Effective configuration for opt-in persistent local browser sessions."""
from dataclasses import dataclass
import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path
import conf
from utils.errors import UsageError


@dataclass(frozen=True)
class LocalBrowserConfig:
    kind: str
    headless: bool
    source: str
    executable_path: str | None = None
    version: str = 'unknown'

    @property
    def launch_options(self):
        source = ({'executable_path': self.executable_path} if self.executable_path
                  else {'channel': self.kind})
        return {**source, 'headless': self.headless, 'no_viewport': True}


def resolve_headless(headless=None):
    value = getattr(conf, 'LOCAL_CHROME_HEADLESS', False) if headless is None else headless
    if type(value) is not bool:
        raise UsageError('LOCAL_CHROME_HEADLESS / headless 必须为布尔值。')
    return value


def resolve_local_browser(*, headless=None, local_browser=None):
    headless = resolve_headless(headless)
    path = getattr(conf, 'LOCAL_CHROME_PATH', '')
    if not isinstance(path, (str, os.PathLike)):
        raise UsageError('LOCAL_CHROME_PATH 必须为空字符串或可执行文件路径。')
    if path:
        executable, kind, version = identify_executable(path)
        return LocalBrowserConfig(kind, headless, f'executable_path={path} resolved={executable}', executable, version)
    kind = local_browser if local_browser is not None else getattr(conf, 'LOCAL_BROWSER', 'chrome')
    if kind not in ('chrome', 'chromium'):
        raise UsageError('local-browser / LOCAL_BROWSER 必须为 chrome 或 chromium。')
    return LocalBrowserConfig(kind, headless, f'channel={kind}')


def _product_kind(product):
    # Chrome for Testing is the full Chromium distribution shipped by Patchright.
    if product in ('Chromium', 'Google Chrome for Testing'):
        return 'chromium'
    if product == 'Google Chrome':
        return 'chrome'
    raise RuntimeError(f'无法可靠识别自定义浏览器产品: {product!r}')


def identify_executable(value):
    """Read product evidence before acquiring any account Profile.

    macOS: bundle product + identifier, validated against the actual executable.
    Windows: executable VersionInfo product. Linux: bounded product --version.
    Neither basename nor UA/CDP strings are identity evidence.
    """
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise RuntimeError(f'自定义浏览器路径不存在或不是文件: {path}')
    if not os.access(path, os.X_OK):
        raise RuntimeError(f'自定义浏览器路径没有执行权限: {path}')
    try:
        if sys.platform == 'darwin':
            with (path.parent.parent / 'Info.plist').open('rb') as source:
                info = plistlib.load(source)
            if info.get('CFBundleExecutable') != path.name or path.parent.name != 'MacOS':
                raise RuntimeError('产品元数据与指定可执行文件不匹配')
            product = info.get('CFBundleDisplayName') or info.get('CFBundleName')
            kind = _product_kind(product)
            names = {product, 'Chrome'} if product == 'Google Chrome' else {product}
            if info.get('CFBundleName') not in names:
                raise RuntimeError('浏览器产品显示名和名称证据冲突')
            expected = {'Google Chrome': 'com.google.Chrome',
                        'Google Chrome for Testing': 'com.google.chrome.for.testing',
                        'Chromium': 'org.chromium.Chromium'}[product]
            if info.get('CFBundleIdentifier') != expected:
                raise RuntimeError('浏览器产品名称和 bundle identifier 证据冲突')
            version = str(info.get('CFBundleShortVersionString') or 'unknown')
        elif sys.platform == 'win32':
            # Fixed command text; executable paths never become PowerShell code.
            result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                '$v=(Get-Item -LiteralPath $env:SAU_BROWSER_PRODUCT_PATH).VersionInfo; $v.ProductName; $v.ProductVersion'],
                env={**os.environ, 'SAU_BROWSER_PRODUCT_PATH': str(path)},
                capture_output=True, text=True, timeout=5, check=True)
            product, version = result.stdout.strip().splitlines()[:2]
            kind = _product_kind(product.strip())
        else:
            result = subprocess.run([str(path), '--version'], capture_output=True,
                                    text=True, timeout=5, check=True)
            match = re.fullmatch(r'(Google Chrome for Testing|Google Chrome|Chromium) ([0-9]+(?:\.[0-9]+){1,3})(?: [^\n]*)?', result.stdout.strip())
            if not match:
                raise RuntimeError('可执行文件没有返回明确的浏览器产品和版本')
            kind, version = _product_kind(match[1]), match[2]
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        raise RuntimeError(f'无法可靠识别自定义浏览器 {path}: {error}') from error
    return str(path), kind, version
