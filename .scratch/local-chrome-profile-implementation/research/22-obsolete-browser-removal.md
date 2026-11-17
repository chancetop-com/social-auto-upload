# 22：废弃浏览器入口与 stealth 删除验证

日期：2026-11-17。基线：`a61628c`。本票遵循用户追加删除授权，覆盖此前保留这些历史调用方/资源的约定；19/20 等实际执行记录保留原样。

## 引用闭包与保留边界

- CodeGraph 和当前工作树审计表明：stealth 实际消费者仅剩旧 `uploader/tk_uploader/main.py` Firefox 实现、未完成/未注册的 `TencentNote` 和 generic `_local_session`；抖音仅有未使用 import。
- 删除上述路径、TencentNote 包导出/专属常量、stealth helper/import、`stealth.min.js` 与 setuptools package-data 条目。移除仅被旧路径消费的 JSON 写回 helper、旧本地启动日志 helper、Tencent base 的旧 Cookie 存在/认证分支及 `os` import。
- 删除只剩旧分支/未注册图文的 `test_publish_cleanup.py`，删除旧会话临时浏览器、JSON 写回和 TencentNote golden 测试；保留平台持久化 cleanup/业务结果覆盖和全部托管测试。
- 正式 TikTok `main_chrome.py` 仍使用 `Tk_Locator` 和 schedule，完整保留。审计过程中一次过度删除 `Tk_Locator` 导致 CLI 导入失败，已完整还原该文件，最终 diff 不包含它。`utils.base_social_media` 的其他旧常量/枚举不属于本票删除对象，没有顺带清理。
- Bilibili biliup、17 平台正式业务、二维码/业务脚本、剪贴板/Humanizer 未改。`close_browser_resources` 仍服务托管 probe 等实际调用，保留。
- generic `browser_session` 无 provider 时抛出说明 `local_browser_session` 必须有 platform/account 的 `ValueError`，在浏览器和旧 Cookie I/O 前停止，不推断本地 Profile。`BrowserSession` 仍共享给持久化本地入口。
- managed 参数保留：headless、account_file、launch/context kwargs、init_script、context_setup、extra_ignored；account_file 从不读写，非空 hints 继续输出原忽略警告/启动日志。provider 的 Start/Stop、所有权、CDP、断开、限流/错误及取消契约保持。

## TDD 与离线结果

Python 均为原仓库 `.venv/bin/python`，cwd 为票据工作树；仅运行隔离临时资料和 browser/provider 边界替身。

1. Red：`python -m unittest tests.test_browser_session.ManagedOnlyBrowserSessionTests -v`。旧实现对无 account_file/有旧路径两种输入都进入本地浏览器，新增拒绝契约失败。
2. Green：移除旧分支后 `tests.test_browser_session tests.test_adspower_browser_session` 共 **44 tests 通过**。
3. Red：`python -m unittest tests.test_runtime_distribution -v`。旧 Firefox 文件、stealth 包资源和 TencentNote 导出三项均失败；删除后通过。
4. `python -m unittest tests.test_runtime_distribution tests.test_browser_session tests.test_adspower_browser_session tests.test_mlx_tencent_baijiahao tests.test_douyin_upload_seam -q`：**105 tests 通过**。
5. 扩展相关回归：**897 tests，895 passed / 2 skipped，51.450s**。两项 skip 是默认关闭的 MLX/AdsPower 实际服务 smoke；没有调用真实 provider。

第 5 项可复现选择器（不包含受控真实浏览器 `*_profile_dom`）：

```python
from pathlib import Path
import unittest
prefixes = ('test_mlx_', 'test_adspower_')
exact = ('test_browser_session', 'test_runtime_distribution', 'test_douyin_upload_seam',
         'test_cli_minimal_config', 'test_bilibili_runtime', 'test_sau_bilibili_cli',
         'test_sau_browser_cli', 'test_runtime_defaults', 'test_local_browser_session',
         'test_local_profile', 'test_review_regressions')
modules = ['tests.' + p.stem for p in sorted(Path('tests').glob('test_*.py'))
           if p.stem.startswith(prefixes) or p.stem in exact
           or p.stem.endswith(('_profiles', '_profile_cli'))]
result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromNames(modules))
raise SystemExit(not result.wasSuccessful())
```

6. 补充发行包保留资源断言后：`python -m unittest tests.test_runtime_distribution tests.test_humanize.PlatformWideGateTests -q`，**4 tests 通过**，包括跨平台交互门禁。

## 打包与文档

- `uv build --offline --out-dir /private/tmp/sau22-dist` 成功生成 wheel 与 sdist。首次沙箱读取 uv cache 受限；授权提升后使用已有缓存离线构建成功，未下载浏览器或更改用户配置。
- zip/tar 内容检查：旧 Firefox/stealth/旧 cleanup 测试均不在发行物；正式 TikTok、TencentVideo、Bilibili runtime 以及 article renderer 脚本/package metadata/NOTICE 存在。
- wheel 解压到 `/private/tmp` 隔离目录，确认 `utils.browser_session` 与 `uploader.tencent_uploader` 从解压包导入后执行 `RuntimeDistributionTests`，**3 tests 通过**。检查脚本首次误写 Bilibili 文件为 `main.py`，修正为实际 `runtime.py`；另一次临时目录 `/var` 与 `/private/var` 路径归一化断言已改用解析路径，无产品改动。
- 更新当前规格/地图/索引、CLI 和安装打包说明。现有 TikTok/Tencent skill 与 agent bootstrap 已指向正式入口，视频号明确仅支持视频，没有旧实现指导，不加入无关实现细节。21 负责目录布局更新。
- `git diff --check` 通过。未执行真实账号、登录、素材上传、发布、删除或 Profile 移动；本票不改共享持久化启动/路径行为，无需重复已有浏览器来源矩阵。
