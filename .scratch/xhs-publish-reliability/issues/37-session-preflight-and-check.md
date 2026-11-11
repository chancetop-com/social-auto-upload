# 37 — 会话与 `check`

**What to build:** 一次发布只开一次浏览器、只打开发布页一次；登录态真伪只由那一次观测判定，网络故障不再被当成"登录失效"。`check` 用同一个判据给出四类明确结果，本地检查成功时顺手把 cookie 写回，登录成功后不再起第二个浏览器复核。

**Blocked by:** 32（`attached` 判定）、35（分类器与文案）.

**Status:** ready-for-agent

## 发布前预检（只有一条零网络快路）

- [x] 本地：账号文件存在 + 会话 cookie 存在 + cookie 未过期（过期时间 ≤0 视为未知、放行）；任一不满足 → `10`，**不启动浏览器**，stderr 给出重新登录命令
- [x] 托管：无前置
- [x] 删除发布链路里的两个预检（本地网络探测 + 托管登录探测）；会话真伪只由导航发布页后的分类判定

## `check` 行为契约

- [x] 本地：前置失败 → invalid / `10`（不起浏览器）；通过 → 带会话打开上下文 → 导航发布页 → 观测
- [x] 托管：建上下文 → 导航发布页 → 观测
- [x] 观测：分类命中 → invalid / `10`，`reason` 走 stderr；分类无且上传入口锚点 `attached`（count ≥ 1）→ valid / `0`（本地原子写回）；分类无且一个锚点都没有 → invalid + "页面结构异常" / `1`；导航 5xx / 超时 / 离开创作域 → `1`（探测失败，不是失效）
- [x] 结果只有两级，不引入"valid-but-degraded"；stdout 仍是 `valid`/`invalid`
- [x] 页面用发布页，锚点用 `attached` 档（后台健康检查不因慢加载误判）

## 登录链路

- [x] 扫码完成判据改为"分类器返回无"，删掉现在并存的另一套 URL 前缀判断与登录框可见判断
- [x] 删除登录后的第二次浏览器复核：改为**同一 context 内**导航一次发布页跑 `probe_session()`；通过 → 原子写回 → success；未通过 → `1`（不判 `10`，避免扫码循环）
- [x] 二维码抓取与轮询节奏不动

## cookie 写回

- [x] 写回矩阵按**结果码**判定：发布成功 `0` / 干跑走完 / 登录复核通过 / 本地 `check=valid` 写回；`1`/`9`/`10` 不写；托管不读不写
- [x] 写盘为临时文件 + 原子替换

## 测试

- [x] 前置三态（有/缺/过期）；`check` 四出口；写回矩阵各一条；登录复核断言只 `new_page` 一次；分类四种 path + `?redirectPath=` 不误判
- [ ] 真机注入：移走账号文件 → `10` 且**无**启动日志；改坏 cookie 一个字符 → 启浏览器 → 分类命中 → `10` 且 stderr **不含** `publish_attempted=true`

## Comments

- 零网络前置：`uploader/xiaohongshu_uploader/main.py` 新增 `local_session_preflight(account_file)`。只读账号文件与 `storage_state` JSON；要求存在名为 `galaxy_creator_session_id` 的 cookie，`expires > 0` 且已过期才失败（缺失 / `expires <= 0` 视为未知放行；JSON 读失败也按前置失败）。失败抛 `LoginRequiredError(reason="login", publish_attempted=False)`，文案复用 `_blocked_message("login","local")`（含 `sau xiaohongshu login --account <账号名>`），CLI 退出 `10`，浏览器未创建。
- 删除的预检：`cookie_auth`（本地网络探测）、`is_logged_in`（托管登录探测）与 `_is_xhs_login_completed` 全部从模块删除；命令层不再 import 二者，发布链路也不再调用 `xiaohongshu_setup`。登录命令的扫码完成判据只剩 `classify_blocked(page) is None`，URL 前缀判断与登录框可见判断已删。
- `probe_session(context) -> (kind, evidence)`：一次 `new_page` → `goto` 发布页（`wait_until="domcontentloaded"`，30s 上限）→ 3s 静置 → `classify_blocked`；命中返回 `("login"|"verification", 当前 URL)`；未命中时逐个检查上传入口选择器，`count >= 1` 返回 `("valid", 当前 URL)`；一个都没有抛 `RuntimeError(...页面结构异常)`。导航超时/异常、5xx、离开创作域同样抛 `RuntimeError`，因此探测失败固定 `1`，不会被当成登录失效。页面在 `finally` 关闭。
- `check`：本地先跑前置；通过后 `check_xiaohongshu_account()` 用 `storage_state` 建上下文 → `probe_session` → 命中抛 `LoginRequiredError`（`10`）、valid 原子写回（`0`）、探测异常由 CLI 映射 `1`；`run()` 在两种异常前都先打印 `invalid`，stdout 保持 `valid`/`invalid`。托管分支 `_check_managed_xiaohongshu()` 只建 context + `probe_session`，不读不写 cookie。
- 登录复核：`xiaohongshu_cookie_gen()` 扫码完成后在同一 context 内跑一次 `probe_session`；通过才 `save_storage_state_atomic()` 并返回 success，未通过返回失败 → 命令层 `RuntimeError` → `1`（不判 `10`）。二维码抓取与 `3s × 100` 轮询未改。
- 原子写回：`save_storage_state_atomic(context, account_file)` 调 `context.storage_state()`（不传 path），写同目录临时文件后 `os.replace`。写点按结果码：本地发布成功 / `--no-publish` 正常返回（`XiaoHongShuVideo.upload`、`XiaoHongShuNote.upload` 的唯一成功路径）、登录复核通过、本地 `check=valid`；`1`/`9`/`10` 均因异常提前退出而不写；托管路径没有 account_file，不读不写。
- 测试：新增 `tests/test_xhs_session.py` 31 条（前置三态 + 未知过期 + 坏 JSON；分类型 path / `?redirectPath=/login` / 锚点缺失 / 5xx / 导航异常 / 离开创作域；本地 `check` 0/10/1 与前置失败零浏览器；托管 0/10/1 且不读 cookie；写回矩阵 0/1/9/10 + 托管；原子替换；登录同 context 复核与失败不写；删除清单静态断言）。既有 XHS 用例迁移到 `probe_session`，Kuaishou 全部保留；`test_adspower_video_platforms.py` 的 XHS 分支改 mock `probe_session`，其他平台仍 mock `is_logged_in`。
- 全量：`python -m unittest discover -s tests -t .` → 1373 tests OK（skipped=2）。
- 真机项：`未验证（无真机环境）` —— ① 移走账号文件后 `10` 且无浏览器启动日志；② 改坏 cookie 一个字符后浏览器启到发布页、分类命中 `10`、stderr 不含 `publish_attempted=true`。
