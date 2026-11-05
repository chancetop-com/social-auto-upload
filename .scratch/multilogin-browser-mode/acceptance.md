# Multilogin X 浏览器模式 — 验收记录（ticket 26）

- 日期：2026-11-05
- 分支：`ticket/26-docs-acceptance`
- 基线：integration tip `576b4eb`
- 环境：macOS（darwin），Python 3.11.11，`patchright==1.64.4`（`pyproject.toml` / `uv.lock`）
- 说明：本记录只运行离线单测；真实 Multilogin 冒烟（ticket 08 / ticket 27）**未执行**，见文末。

## 1. 执行命令与结果

### 全量单测

```bash
cd /Users/chancetio/Desktop/Web/social-media-auto-upload/sau-worktrees/t26
/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python \
  -m unittest discover -s tests
```

结果：

```
Ran 577 tests in 63.703s
FAILED (failures=5, errors=1, skipped=1)
```

与基线一致，**无新增失败**。失败/错误均为 feature 之前已存在：

| 类型 | 测试 | 原因 |
| --- | --- | --- |
| FAIL | `test_douyin_declaration.DouyinDeclarationTests.test_legacy_positional_runtime_flags_keep_their_meaning` | 历史参数顺序漂移（`collection_name` 插在 `publish_strategy` 前） |
| ERROR | `test_douyin_declaration.DouyinDeclarationTests.test_declaration_failure_closes_browser_resources` | 同一历史声明测试的资源清理用例 |
| FAIL | `test_instagram_uploader.InstagramBrowserRegressionTests.test_optional_prompts_present_absent_and_failed_dismissal` | 真实 Chrome 下 dialog 数量 2 ≠ 1 |
| FAIL | `test_xiaohongshu_uploader.XiaohongshuUploaderTests.test_video_fill_meta_uses_desc_then_first_tag` | 超时期望 2000ms，实现 4000ms |
| FAIL | `test_xueqiu_uploader.XueqiuInputTests.test_markdown_keeps_heading_and_image_position` | macOS `/private/var` 与 `/var` 路径差异 |
| FAIL | `test_xueqiu_uploader.XueqiuInputTests.test_relative_images_stay_between_original_paragraphs` | 同上 |

跳过项为 `tests.test_mlx_smoke` 的 opt-in 真实冒烟用例（未设置 `SAU_MLX_SMOKE=1`）。`test_dayu_uploader...test_processing_has_a_deadline` 本次未出现计时抖动。

### 聚焦 MLX 模块

```bash
cd /Users/chancetio/Desktop/Web/social-media-auto-upload/sau-worktrees/t26
/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest \
  tests.test_multilogin_cli \
  tests.test_douyin_mlx_check \
  tests.test_douyin_upload_seam \
  tests.test_multilogin_client \
  tests.test_browser_session \
  tests.test_mlx_smoke \
  tests.test_mlx_xhs_kuaishou \
  tests.test_mlx_tencent_baijiahao \
  tests.test_mlx_alipay_weibo \
  tests.test_mlx_hupu_dayu \
  tests.test_mlx_youtube \
  tests.test_mlx_meta \
  tests.test_mlx_zhihu_xueqiu \
  tests.test_mlx_tiktok
```

结果：

```
Ran 443 tests in 6.402s
OK (skipped=1)
```

唯一的 skip 仍是 `test_mlx_smoke` 的 opt-in 真实冒烟用例。

## 2. spec §15 验收清单逐条结果

| # | 验收项 | 结果 | 证据 |
| --- | --- | --- | --- |
| 1 | 无 token 时，所有平台旧命令解析与行为不变；本地单测全绿 | PASS（有基线例外） | `tests.test_multilogin_cli`：`test_unset_token_means_local_mode`、`test_empty_token_means_local_mode`、`test_whitespace_token_means_local_mode`、`test_local_mode_ignores_multilogin_flags`、`test_local_missing_account_exits_2_for_every_login_and_check`；各 `test_mlx_*` 模块的 local golden / legacy path 用例。全量 577 条中仅保留上表 5F/1E 既有失败，无新增。 |
| 2 | MLX 下 check：已登录 0、未登录 10、Launcher 故障 1、缺参 2 | PASS | `tests.test_douyin_mlx_check`（0/10/1/2 四个分支）；`test_mlx_xhs_kuaishou`、`test_mlx_tencent_baijiahao`、`test_mlx_alipay_weibo`、`test_mlx_hupu_dayu`、`test_mlx_youtube`、`test_mlx_meta`、`test_mlx_zhihu_xueqiu`、`test_mlx_tiktok` 中均有同名 `check_*_returns_0/10/1/2` 用例。 |
| 3 | MLX 下 upload：成功 0、登录失效 10、上传失败 1；成功后 Stop 被调用一次 | PASS | `tests.test_douyin_upload_seam`：`test_upload_video_mlx_passes_none_account_and_one_session`、`test_upload_mlx_logged_out_returns_10_and_skips_upload`、`test_upload_mlx_failure_still_exits_session_once`；各平台模块的 `upload_*_returns_0/10/1` 与 `test_upload_mlx_stops_profile_exactly_once`（`test_mlx_alipay_weibo`、`test_mlx_hupu_dayu`、`test_mlx_tiktok`）。 |
| 4 | Start 成功但 connect 失败：退出 1，且 Profile 被 Stop | PASS | `tests.test_browser_session.test_connect_failure_queries_status_once_enriches_error_and_stops`（3 次连接、status 一次、错误含 Docker 提示、最后事件为 stop）；CLI 层由 `test_douyin_mlx_check.test_probe_error_returns_1...` 等覆盖 1 的映射。 |
| 5 | 取消 / KeyboardInterrupt：Stop 已发出（shield） | PASS | `tests.test_browser_session.test_cancellation_issues_stop_under_shield`。说明：这是 asyncio 取消级验证，没有做真实进程 `Ctrl-C` 端到端测试；CLI 不捕获 `KeyboardInterrupt`，`finally` 仍执行 Stop。 |
| 6 | MLX 全程未调用 `new_context` / `storage_state` / `add_init_script` / `grant_permissions` | PASS | `tests.test_browser_session.test_happy_path_lifecycle_and_forbidden_local_apis_are_never_used`、`test_forbidden_apis_raise_loudly_if_mlx_touches_them`；各平台 `*_consumes_injected_session_without_forbidden_api`、`test_*_mlx_skips_cookie_auth_and_grant_permissions`、`test_mlx_upload_only_uses_injected_context`。 |
| 7 | MLX 未读写任何 `cookies/*.json`；token 未出现在日志/异常 | PASS（日志为代码审查） | 不读写 cookie：`test_mlx_xhs_kuaishou.test_*_mlx_never_reads_cookies`、`test_mlx_alipay_weibo.test_mlx_validation_skips_cookie_auth_and_cookie_existence`、`test_douyin_upload_seam.test_mlx_validation_skips_cookie_auth`、`test_mlx_tiktok.test_cli_never_resolves_a_cookie_file`，以及各模块断言 `storage_state_calls == []`。token：`test_multilogin_client.MultiloginSanitisationTests.test_client_repr_never_contains_token`、`test_multilogin_client.test_start_locked_profile_preserves_mlx_error_and_does_not_leak_token`、`test_multilogin_cli.test_token_never_appears_in_errors`、`test_browser_session.test_connect_failure_...` 的 `assertNotIn(TOKEN, message)`。**未专门捕获 loguru 日志做断言**；代码审查确认启动日志只记录 `profile_id` / `folder_id` / `port`，停止日志只记录 `profile_id`，不记录 token 或 Authorization。 |
| 8 | Profile 已运行时：退出 1，原始 lock 错误可见，且未 Stop 该 Profile | PASS | `tests.test_multilogin_client.test_start_locked_profile_preserves_mlx_error_and_does_not_leak_token`（保留 MLX `error_code`/message）；`tests.test_browser_session.test_start_failure_does_not_stop_someone_elses_profile`。Start 失败发生在 `try` 之前，不会进入 Stop。 |
| 9 | TikTok：无 token 退出 1；MLX check/upload 可用；验证码 10 | PASS | `tests.test_mlx_tiktok.test_check_local_exits_1`、`test_upload_video_local_exits_1`、`test_login_local_exits_1`；`test_logged_in_returns_0`、`test_logged_out_returns_10`、`test_upload_success_returns_0_and_uses_one_session`、`test_captcha_mid_upload_raises_login_required`。 |
| 10 | `patchright==1.64.4` 现有测试用例回归通过（本地模式不做真实账号完整验证） | PASS（无真实账号回归） | `pyproject.toml` 与 `uv.lock` 均 pin `1.64.4`；全量单测无新增失败。真实平台发布、风控和指纹差异按 spec §13 不自动化。 |
| 11 | 文档包含部署前提、调度责任、账号一致性风险 | PASS | `README.md`、`docs/CLI.md`（Multilogin X 模式）、`docs/xueqiu.md`、`skills/{douyin,xiaohongshu,youtube,tiktok}-upload/SKILL.md`、`skills/social-auto-upload/SKILL.md`、`docs/skill-distribution.md`。 |

### ticket 26 补充验收项

| 项 | 结果 | 证据 |
| --- | --- | --- |
| MLX check 的 0/10/1/2 | PASS | 同 §15 #2 |
| MLX upload 的 0/10/1 | PASS | 同 §15 #3 |
| connect 失败仍 Stop | PASS | 同 §15 #4 |
| 取消时 shield 发 Stop | PASS | 同 §15 #5 |
| Profile 已运行时不误 Stop | PASS | 同 §15 #8 |
| token 不出现在日志/异常 | PASS（异常已测，日志代码审查） | 同 §15 #7 |
| MLX 不读写 cookie | PASS | 同 §15 #7 |

## 3. 未执行 / 未覆盖

- **真实 MLX 冒烟未执行**：ticket 08 与 ticket 27 的真实账号冒烟**没有运行**。`tests.test_mlx_smoke` 默认 skip，本次全量与聚焦运行中的 1 个 skip 就是该用例；未设置 `SAU_MLX_SMOKE=1`，也没有可用的 `MLX_API_TOKEN` / Folder / Profile。因此本记录不声称真实 Launcher、CDP、Mimic 内核或 `no_defaults=True` 已验证。
- 未做真实平台发布、验证码/2FA 人工处理、风控、代理指纹、Docker launcher、跨机拓扑、前端联调；这些按 spec §13 明确不自动化。
- `KeyboardInterrupt` 只有 asyncio 取消级单测，没有真实进程信号级测试。
- token 的日志卫生没有专门 loguru 捕获测试，只有异常/错误文本与 `repr` 断言，加上代码审查。

## 4. 遗留风险

- 真实 MLX 行为（尤其 `connect_over_cdp(..., no_defaults=True)` 与 Mimic）仍待 ticket 08 回填；失败时按 spec §12 回退为不传 `no_defaults`。
- Docker launcher 的 CDP 端口映射未闭环，v1 只给错误提示。
- MLX 跳过本地身份绑定：知乎/雪球/大鱼号/Instagram 的 `profile_id` 错配由调度侧承担。
- 小红书/百家号在 MLX 下不授予定位权限，真实发布是否依赖定位未验证。
- 429 限流不在 CLI 内等待，由调度侧重试。
