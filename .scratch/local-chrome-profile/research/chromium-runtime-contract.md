# Patchright 配套 Chromium 的安装与启动契约

核对日期：2026-11-17（Asia/Shanghai）。用途：当前 local-chrome-profile 的 wayfinder 补充资料；只确定可供选择的契约，不实现代码、不改票或决策图。本次仅访问官方资料、读取本地已安装包，并执行 CLI help；没有安装、下载或启动浏览器，没有运行平台登录或上传验证。

后续决策说明：用户已在[本地 Chrome 启动参数与失败契约](../issues/02-chrome-launch-contract.md)确认保留通用自定义路径覆盖，且 Chrome / Chromium 均按需安装。本文关于不设置 `executable_path` 的建议仅适用于选择 Patchright 配套浏览器的路线，不限制用户通过旧配置指定兼容 Chromium；最终项目政策以决策票为准。

## 结论

保留系统 Google Chrome 的默认 `channel="chrome"`；用户主动选择配套 Chromium 时，建议有头、无头都明确传 `channel="chromium"`，只切换 `headless`。在不设置 `executable_path` 的前提下，省略 channel 会使 `headless=True` 选择另一个 `chromium-headless-shell` 可执行文件；显式 `channel="chromium"` 才能让两种模式选择同一个完整浏览器。此结论同时得到官方文档和本地固定版本 driver 的分支支持。[Playwright Chromium 模式][pw-browsers]、[本地 driver 选择分支][local-selection]

安装基线是项目环境中的 `uv run patchright install chromium`。如果该功能始终使用上述完整浏览器契约，也可以采用 `uv run patchright install --no-shell chromium`，省去 headless shell；`--only-shell` 不适合需要有头登录的路线。[Patchright 安装说明][patchright-readme]、[Playwright 安装选项][pw-browsers]、[本地安装目标解析][local-install-targets]

这是项目选择建议；Patchright README 的推荐示例仍是 Chrome、persistent context、`headless=False`、`no_viewport=True`。README 并未承诺 Chromium 或无头模式与该推荐示例拥有相同的平台登录效果。[Patchright README][patchright-readme]

## 版本边界与名称

- 仓库固定 `patchright==1.64.4`，本地 Python distribution 只读查询也返回 `1.64.4`。该 wheel 内的 `patchright-core` 元数据实际为 **`1.64.3`**，不能把 Python 包版本和内置 driver 版本混写。[项目依赖][project-deps]、[锁文件][project-lock]、[本地 driver 元数据][local-package]
- 本地 `browsers.json` 将 `chromium` 与 `chromium-headless-shell` 都固定到 revision `1248`、browserVersion `156.0.8078.4`。前者 title 是 **Chrome for Testing**，后者是 **Chrome Headless Shell**。本文“配套 Chromium”指 Patchright CLI/API 名称 `chromium` 对应的完整浏览器，不表示系统稳定版 Chrome，也不表示任意 PATH 中的 Chromium。[本地浏览器清单][local-browsers]、[本地可执行文件注册][local-registry]
- 官方网页为核对当日的滚动文档；本文的具体选择逻辑、CLI 选项及版本号已用本地固定包交叉检查。以后升级 Patchright 时，应重新检查包内清单、CLI help 和启动选择分支，不沿用本文的 revision 或浏览器版本。[本地 CLI 定义][local-cli]、[Playwright 版本与浏览器绑定说明][pw-browsers]

## 安装契约

以下是拟采用的命令，**本次没有执行安装**。前提是从本项目使用已同步的固定 Patchright 环境；不要拿另一套全局 Playwright/Patchright 的 CLI 代替。Patchright 的 console entry point 指向 `patchright.__main__:main`，它转发到自己随包提供的 driver CLI。[Patchright README][patchright-readme]、[本地 Python CLI 转发][local-main]

```sh
uv run patchright install chromium
```

| 命令尾部 | 此固定 driver 选择的浏览器目标 | 适用情况 |
| --- | --- | --- |
| `install chromium` | 完整 `chromium` 和 `chromium-headless-shell` | 同时保留有头、完整浏览器无头、默认 shell 无头三条能力 |
| `install --no-shell chromium` | 完整 `chromium` | 有头与 `channel="chromium"` 无头；建议契约可用此精简方式 |
| `install --only-shell chromium` | 仅 `chromium-headless-shell` | 省略 channel 的 shell 无头路线，不能满足完整浏览器有头启动 |
| `install chromium-headless-shell` | 显式选择 shell | 同上，不代替完整浏览器安装 |

表中只列浏览器目标；本地解析器还加入 FFmpeg，Windows 会加入 winldd。`--no-shell` 与 `--only-shell` 不能同时指定。`--with-deps` 是额外安装系统依赖的选项，不改变 full/shell 的选择含义。[本地安装解析][local-install-targets]、[本地 CLI 执行分支][local-install-command]、[Playwright 安装文档][pw-browsers]

浏览器安装和启动要使用相同的浏览器缓存配置；若设置 `PLAYWRIGHT_BROWSERS_PATH`，两步保持一致，且优先使用绝对路径。Patchright 本地 driver 确实读取这个变量；不需要手工寻找缓存中的 binary 并填入 `executable_path`。[Playwright 缓存配置][pw-cache]、[本地缓存路径解析][local-cache]

缺少目标 binary 时，本地 driver 报错并给出安装提示；正常启动路径不负责下载，也不会在 `chrome` 与 `chromium` 间自动回退。项目可以把缺失错误转成对应安装指引，但是否实现友好提示属于后续设计。[本地可执行文件注册][local-registry]、[本地启动选择][local-launch]

## 启动契约与有头／无头差异

以下是未执行的调用示意，`profile_dir` 表示专用自动化用户数据目录：

```python
context = await p.chromium.launch_persistent_context(
    user_data_dir=profile_dir,
    channel="chromium",
    headless=False,  # 无头任务改为 True，channel 保持不变
    no_viewport=True,
)
try:
    ...
finally:
    await context.close()
```

本地 Python API 明确支持这些参数；`launch_persistent_context` 返回该浏览器的持久化 context，关闭它会关闭浏览器。同一个用户数据目录不能同时被多个浏览器实例使用，不能把日常 Chrome 的主目录作为自动化目录。[官方 persistent context API][pw-api]、[本地 API 签名与说明][local-api]

在没有 `executable_path`、也没有调试器强制覆盖运行模式的通常调用下，选择关系为：

| `channel` | `headless` | driver 选择 |
| --- | --- | --- |
| `"chrome"` | `False` / `True` | 系统 Chrome，对应模式启动 |
| `"chromium"` | `False` | 配套完整浏览器，有头 |
| `"chromium"` | `True` | 配套完整浏览器的新无头模式 |
| 省略 | `False` | 配套完整浏览器，有头 |
| 省略 | `True` | 配套 headless shell |

这一表格来自本地 `getExecutableName(options)` 分支；官方 API 也把 `channel="chromium"` 定义为选择新无头模式的入口。`headless` 默认值是 `True`，所以调用处应显式传值。driver 会替 headless 模式加入启动参数，无需额外拼接 `--headless` 或 `--headless=new`。[本地选择分支][local-selection]、[本地默认 headless][local-default-headless]、[本地 headless 参数][local-headless-args]、[官方 API][pw-api]

`no_viewport=True` 表示不强制默认固定 viewport。该参数并不选择浏览器，也不是无头开关；本地 Python 转换为 `noDefaultViewport=True`，context 参数校验没有禁止与 `headless=True` 配合。它适用于上述两种调用，但不能据此承诺两种模式的页面尺寸、渲染或平台行为一致。与 `device_scale_factor` 或启用的 `is_mobile` 组合存在校验冲突，不应在本契约中混入。[官方 no_viewport API][pw-api]、[本地参数转换][local-viewport]、[本地 context 校验][local-validation]

## `channel` 与 `executable_path`

- `channel` 是浏览器分发／注册目标名，不是路径。`chrome` 选择系统 Chrome；`chromium` 选择当前 driver 清单对应的完整浏览器。两者仍通过 `p.chromium` 这个 BrowserType 使用。[官方 API][pw-api]、[本地选择分支][local-selection]
- 启动参数 `executable_path` 指定要运行的实际文件，替代正常注册表选择。此固定 driver 先解析显式路径，成功后不会再通过 channel 选择 binary；因此不能靠同时传 `channel="chromium"` 来保证一个自定义路径就是配套版本。使用配套版本时不应设置该参数；项目另保留用户明确选择的自定义路径路线，其优先级见上述最终决策票。[官方 executable_path 参数][pw-api]、[本地启动选择][local-launch]、[本地自定义路径检查][local-executable]
- `p.chromium.executable_path` **属性**只报告预期的配套 browser 路径，不负责安装，也不证明文件存在或可运行。它和调用时的同名参数用途不同。[官方 executable_path 属性][pw-executable-property]

Chrome 安装与 ARM64 结论继续使用现有 [Chrome ARM64 安装研究][chrome-note]，本文件不重新选择 Chrome 安装方案。

## 本次证据与验证上限

可复查的只读命令如下；本次已通过同等元数据脚本及此 CLI help 核对：

```sh
.venv/bin/python -B -c 'from importlib.metadata import version; print(version("patchright"))'
.venv/bin/python -B -m patchright install --help
```

另通过只读脚本检查 distribution entry points、driver `package.json`、`browsers.json`、Python API 及 `coreBundle.js` 的相关分支。未运行 `uv run patchright install chromium`、任何浏览器启动、用户数据目录迁移或平台请求。因此这份资料证明的是固定版本的安装目标和启动选择契约，**不证明机器已装好对应 binary、浏览器实际启动成功、Chrome profile 可直接复用到 Chromium，或任何平台登录／上传有效**。这些结论需要后续独立验证。

[patchright-readme]: https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python#install-it-from-pypi
[pw-browsers]: https://playwright.dev/python/docs/browsers#chromium-new-headless-mode
[pw-cache]: https://playwright.dev/python/docs/browsers#managing-browser-binaries
[pw-api]: https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context
[pw-executable-property]: https://playwright.dev/python/docs/api/class-browsertype#browser-type-executable-path
[project-deps]: /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/pyproject.toml:14
[project-lock]: /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/uv.lock:245
[local-package]: /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/lib/python3.11/site-packages/patchright/driver/package/package.json:1
[local-browsers]: /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/lib/python3.11/site-packages/patchright/driver/package/browsers.json:4
[local-main]: /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/lib/python3.11/site-packages/patchright/__main__.py:6
[local-selection]: /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/lib/python3.11/site-packages/patchright/driver/package/lib/coreBundle.js:47042
[local-registry]: /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/lib/python3.11/site-packages/patchright/driver/package/lib/coreBundle.js:36395
[local-install-targets]: /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/lib/python3.11/site-packages/patchright/driver/package/lib/coreBundle.js:37112
[local-install-command]: /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/lib/python3.11/site-packages/patchright/driver/package/lib/coreBundle.js:74773
[local-cli]: /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/lib/python3.11/site-packages/patchright/driver/package/lib/coreBundle.js:78466
[local-cache]: /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/lib/python3.11/site-packages/patchright/driver/package/lib/coreBundle.js:36336
[local-launch]: /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/lib/python3.11/site-packages/patchright/driver/package/lib/coreBundle.js:43430
[local-api]: /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/lib/python3.11/site-packages/patchright/async_api/_generated.py:4125
[local-default-headless]: /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/lib/python3.11/site-packages/patchright/driver/package/lib/coreBundle.js:43536
[local-headless-args]: /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/lib/python3.11/site-packages/patchright/driver/package/lib/coreBundle.js:47010
[local-viewport]: /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/lib/python3.11/site-packages/patchright/_impl/_browser_type.py:275
[local-validation]: /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/lib/python3.11/site-packages/patchright/driver/package/lib/coreBundle.js:55126
[local-executable]: /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/lib/python3.11/site-packages/patchright/driver/package/lib/coreBundle.js:43578
[chrome-note]: /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.scratch/local-chrome-profile/research/chrome-arm64-installation.md
