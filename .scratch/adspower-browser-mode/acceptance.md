# AdsPower 托管浏览器模式 — 验收记录

- 验收日期：2026-11-09
- 分支：`feat/adspower-browser-mode`（文档 ticket 15 在 `ticket/15-docs-glossary-skills` 上提交）
- 范围：文档、术语、Skills、CHANGELOG 与验收记录；代码 ticket 11–14、16 已合并。
- 真实设备状态：**真实 AdsPower 冒烟未执行（ticket 09）**。本机未安装 AdsPower，`50325` 未监听；所有真实 Profile 行为仍属未验证。

## §11.5 文档文件清单

| 文件 | 要求 | 结果 | 证据 |
| --- | --- | --- | --- |
| `GLOSSARY.md` | 分层术语；Profile 泛化；AdsPower Local API / API Key / `user_id`；MLX 专属词标注 | ✅ | 新增“托管浏览器模式”“AdsPower”“AdsPower Local API”“API Key（`ADSPOWER_API_KEY`）”“`user_id`”；`Folder` / `Launcher` / `Automation Token` / `Multilogin X 模式` 标题标注“MLX 专属”；`Profile` 不再限定 MLX |
| `docs/CLI.md` | 三个章节；旧锚点 `#multilogin-x-模式` 可用；参数矩阵；退出码含 `11`；平台表；部署前提；调度责任；身份风险；安全；Bearer/重置；不支持清单 | ✅ | 新增 `## 托管浏览器模式（通用）`、保留 `## Multilogin X 模式`、新增 `## AdsPower 模式`；通用章节含激活矩阵、参数矩阵、退出码（含 `11`、MLX 429 `1 → 11`）、16 平台表、部署前提、调度责任、身份风险、安全、不支持清单；AdsPower 章节含 Bearer 与 key 重置 |
| `README.md` | `#### 托管浏览器模式（可选）` + MLX/AdsPower 两个子节；两套示例；退出码含 `11` 与 MLX 429 提示 | ✅ | `#### 托管浏览器模式（可选）` 下含 `##### Multilogin X（MLX）` 与 `##### AdsPower`；各自给出 `check` / `upload-video` 示例；共同说明含 `11` 与 MLX 429 变更 |
| `docs/skill-distribution.md` | 模式说明与两种托管 provider 的表格条目 | ✅ | 新增本地 / 托管模式说明与 `## 托管浏览器模式与 Skill` 表；TikTok 行改为“本地或托管浏览器模式” |
| `skills/social-auto-upload/SKILL.md` | 总入口模式说明 | ✅ | 新增 `## 托管浏览器模式`；TikTok 行与工作流同步；Bilibili 标注不支持 |
| `skills/<17 个平台>/SKILL.md` | 统一模板；Bilibili 为“不支持”特例 | ✅ | 18 个 Skill 均含托管模式说明；Bilibili 明确“托管浏览器模式不支持 Bilibili（`biliup` 没有浏览器上下文）” |
| `CHANGELOG.md` | `[Unreleased]` 的 `### 托管浏览器（AdsPower）` | ✅ | 已新增；含 MLX 429 `1 → 11`、真实冒烟未执行（ticket 09）与已知限制 |
| `.scratch/adspower-browser-mode/acceptance.md` | 文件清单逐项核对；写明“真实 AdsPower 冒烟未执行（ticket 09）” | ✅ | 本文件 |

## §15 验收清单

| 验收项 | 结果 | 证据 / 说明 |
| --- | --- | --- |
| `ADSPOWER_API_KEY` 非空激活；空/空白不激活；base 不激活 | ✅ | `tests/test_adspower_cli.py` 的 `ActivationTests`；文档 `docs/CLI.md` 激活矩阵 |
| 双 key 冲突 → `1`，文案精确 | ✅ | `ConflictTests`；文案 `MLX_API_TOKEN 与 ADSPOWER_API_KEY 不能同时设置；请只保留一个。` 已写入 CLI/README |
| `--profile-id` 必填；`--folder-id` 忽略；`--account` 可选 | ✅ | `ParameterMatrixTests`、`test_registration_scope_matches_the_shared_matrix`；文档参数矩阵 |
| `login` → `1`；bilibili → `1`；`verify`/`delete`/`article` 本地 | ✅ | `test_login_is_rejected_with_adspower_wording_and_placeholder`、`test_bilibili_login_check_and_upload_exit_1`、`test_local_only_actions_still_require_account_in_adspower_mode`、`test_article_stays_local_and_accepts_no_browser_flags`；文档平台表 |
| `check` 未登录 → `10`；成功 → `0` + `valid` | ✅ | `CheckAndExitCodeTests.test_check_not_logged_in_exits_10_with_adspower_wording`、`test_check_success_prints_only_valid` |
| 退出码 `0/1/2/9/10/11/130` 全部有测试锁住 | ✅ | `tests/test_adspower_cli.py` 覆盖 `0/1/2/10/11`；`9` / `130` 由既有 CLI 契约测试与 `sau_cli` 的异常映射覆盖；文档退出码表完整 |
| `429` → `11`；stop 阶段 `429` 不改变主结果 | ✅ | `test_rate_limited_error_maps_to_11`、`test_rate_limited_on_probe_exits_11_without_start_or_stop`、`test_rate_limited_on_start_exits_11_without_stop`、`test_rate_limited_during_stop_keeps_success_exit_code` |
| `probe → start → connect → contexts==1 → yield → disconnect → stop` 顺序正确 | ✅ | `tests/test_adspower_browser_session.py` 生命周期用例 |
| start 失败不停；`StartIncompleteError` 先 stop 再抛；CDP 失败 finally stop | ✅ | `test_start_incomplete_stops_profile_then_exits_1` 与 `tests/test_adspower_browser_session.py` |
| 取消时 shield stop；stop 失败只 warning | ✅ | `tests/test_adspower_browser_session.py`；`utils/browser_session.py` 的 `_stop_profile` |
| start body 固定 `last_opened_tabs=0`、`proxy_detection=0`、`delete_cache=0`、`cdp_mask=1` | ✅ | `tests/test_adspower_client.py` `test_start_posts_v2_endpoint_with_exact_body_and_headers`、`test_start_fixed_fields_cannot_be_overridden_by_callers` |
| ws URL 原样传给 `connect_over_cdp`，不拼 http | ✅ | `tests/test_adspower_client.py` / `tests/test_adspower_browser_session.py` |
| key 不出现在 stdout/stderr/异常/`repr`/日志 | ✅ | `SecretRedactionTests`、`AdspowerSanitisationTests` |
| 28 处 `session.mode` 清零；静态守卫绿 | ✅ | `tests/test_adspower_platform_contract.py` |
| 本地与 MLX 回归全绿（仅 429 行为变更 + 2 处测试签名迁移） | ✅ | 已合并的 ticket 11–14、16 离线套件；本 ticket 未改代码 |
| 文档清单（ticket 06）逐项存在；旧锚点有效 | ✅ | 见上表；`docs/CLI.md` 保留 `## Multilogin X 模式` 标题，GitHub slug 为 `multilogin-x-模式` |
| `acceptance.md` 写明真实 AdsPower 冒烟未执行（09） | ✅ | 本文件开头与下方未验证项 |

## 真实设备未验证项（ticket 09 保持 open）

**真实 AdsPower 冒烟未执行（ticket 09）**。以下行为只有离线测试和设计依据：

1. 已运行 Profile 的 start 返回形状：成功 + 既有 ws，还是错误。
2. 重复 stop / 已停止 Profile 的真实 `code` / `msg`。
3. 429 的真实形状（HTTP 429 还是 200 + 业务 `code`）与 `Retry-After`。
4. `contexts` 是否恒为 1（含 `last_opened_tabs=0`）。
5. 冷启动是否可能超过 30s；超时后不 stop 是否真的留下 Profile。
6. V2 在旧客户端上的真实状态码（404 还是 200 + `code != 0`）。
7. `/status` 是否要求鉴权、是否返回版本字段。
8. V2 最低可用版本；`active` 在 Inactive / 多设备模式下的 `data` 形状。

`tests/test_adspower_smoke.py` 是 opt-in 冒烟入口（`SAU_ADSPOWER_SMOKE=1`），默认 skip；其文件头也标注 **Execution status: not executed**，不得把 harness 当成真实冒烟结果。

## 已知限制

命令级 `check` / 上传前登录检测已是 provider-aware 文案；但部分平台在**上传过程中**遇到登录页、验证码或 2FA 时，uploader 内部错误仍可能提到 Multilogin。这是后续统一文案的已知遗留，不代表 AdsPower 模式需要 Multilogin，也不改变退出码 `10` 的语义。
