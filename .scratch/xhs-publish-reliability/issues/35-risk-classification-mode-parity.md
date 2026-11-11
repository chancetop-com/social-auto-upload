# 35 — 风控分类与模式一致性

**What to build:** 本地模式和托管模式用同一个判据识别登录页/人机验证页，都退出 `10`。本地模式不再因为少了一道托管分支就完全看不见登录页；文案按 provider 说对名字（AdsPower 用户不会再被指去 Multilogin）。同时删掉一批随新语义失效的死代码。

**Blocked by:** 33（登录锚点与可见性判定）.

Status: resolved

**分类器判据（唯一一份，只读、不注入脚本）**

- [x] 只比较 URL 的 path，不读 query、不做 unquote：`/website-login/captcha` → verification；`/website-login`（裸与未知子路径）→ login；`/login` → login；其余 → 无
- [x] path 未命中时补强：登录框按 `visible` 档可见 → login；path 命中则不查 DOM
- [x] 不做非跳转式验证码弹层识别；读失败按"不拦截"处理
- [x] `?redirectPath=/login` 一类 query 不得误判

**模式一致性**

- [x] 8 处 `if multilogin:` 门全部删除；参数由布尔 `multilogin` 换成三值 `mode`，调用点传会话模式
- [x] 四句文案在 raise 点拼：本地/托管 × login/verification；`{App}` 取公开的 provider 标签；不带 profile id；本地句只给账号名占位符
- [x] `publish_attempted=True` 时在上句后追加"发布可能已发出：重跑前请先确认该笔记是否存在。"
- [x] `reason` 与 `publish_attempted` 字段保留，供测试与日志断言

**检查点**

- [x] C1：导航到发布页后立刻分类，命中 → `10`（未派发）
- [x] C2：每个可能超过 2s 的等待循环每轮查一次（视频预览轮询、图文标题等待；ARM 轮询归 36），命中 → `10`（未派发）
- [x] 检查点抛出的登录失效错误不得被宽 `except Exception` 吞掉

**删除清单**

- [x] 删除：登录 URL 子串表、`_raise_if_login_required`、发布失败词表与对应异常及其两处 `except`、失败提示扫描、未使用的成功 URL 常量、无调用点的上传错误处理、无调用点的原创声明检查

**验证**

- [x] **核心回归**：本地模式用坏 cookie 打开发布页 → 判出 login → `10`，且 stderr 不含 `publish_attempted=true`
- [x] 四文案 × 两模式断言；AdsPower 出现且 Multilogin 不出现
- [x] `check`/登录链路可先不动（归 37）

## Comments

- 分类器：`utils/blocked.py` 新增 `BlockedKind` / `BlockedRules` / `classify(page, rules, *, visibility_check=None)`。只读 `main_frame.url`（缺席时回退 `page.url`）的 path；最长前缀优先，按路径段边界匹配（`/login` 命中 `/login`、`/login/step2`，不命中 `/loginx`）；path 未命中才查登录框，默认 `utils.dom.check(locator, "visible")`；任何读取失败返回 `None`。零平台 import（仅 patchright 类型之外的 stdlib + `utils.dom`）。
- 小红书接线：`XHS_BLOCKED_RULES` = `login_paths=("/website-login", "/login")`、`verification_paths=("/website-login/captcha",)`、`login_box_selector="div[class*='login-box']"`；`classify_blocked(page)` 是唯一入口。`?redirectPath=/login` 只读 path，因此不误判。
- 文案：`_blocked_message(kind, mode, *, publish_attempted)` 在 raise 点拼四句之一（本地/托管 × login/verification），`{App}` = `utils.browser_session.provider_label(mode)`，无 profile id，本地 login 句只给 `<账号名>` 占位符；`publish_attempted=True` 追加固定后缀。`_check_blocked(page, mode, *, publish_attempted)` 抛 `LoginRequiredError(message, reason=kind, publish_attempted=...)`。
- `publish_attempted` 现取：两个入口都在函数开头定义 `publish_clicked = False`，C1/C2 都传这个变量；后续 C3/C4（ticket 36）可继续复用同一变量，禁止按调用点硬编码。
- 检查点：C1 在 `goto` + `after_navigate` 之后、`wait_for_url` 之前；C2 在视频预览轮询与图文标题等待的**每轮顶部、try 之外**，因此 `LoginRequiredError` 不会被轮询的宽 `except Exception` 吞掉（两条回归用例用“轮询先翻转 URL 再抛普通异常”验证）。
- 删除：`_XHS_PUBLISH_FAILURE_KEYWORDS`、`XhsPublishRejectedError` 及两处 `except`、`_find_publish_failure`、`XHS_PUBLISH_SUCCESS_URL_PATTERN`、`_LOGIN_URL_MARKERS`、`_raise_if_login_required`、`XiaoHongShuVideo.handle_upload_error`、`check_original_declaration`。Kuaishou 的同名 `_raise_if_login_required` 未动。
- 模式参数：`upload_video_content` / `upload_note_content` 的 `*, multilogin: bool = False` → `*, mode: str`；`upload_in` 传 `session.mode`。8 处 `if multilogin:` 门全部消失。
- `LoginRequiredError` 增加关键字字段 `reason="login"` / `publish_attempted=False`，旧的 `LoginRequiredError(message)` 位置参数构造保持可用。
- 测试：`tests/test_xhs_blocked.py` 29 条（path 矩阵、query 不误判、路径段边界、最长前缀、可见/隐藏登录框、path 命中短路 DOM、URL/DOM 读失败、两种 `visibility_check` 形状、四文案 × 本地/Multilogin/AdsPower、后缀、旧构造、C1 字段、本地坏 cookie → 真实 `sau_cli.main` 退出 10 且 stderr 无 `publish_attempted=true`、视频/图文 C2 不被吞、删除清单静态断言、8 门静态断言）。既有 XHS 用例改用 `mode=`；`test_mlx_xhs_kuaishou.py` 的 XHS 登录跳转断言保留、旧 `/captcha/verify` 用例改为 `/website-login/captcha`（`reason="verification"`），Kuaishou 用例全部保留。
- 全量：`python -m unittest discover -s tests -t .` → 1284 tests OK（skipped=2）。
- 真机项：`未验证（无真机环境）` —— ① Multilogin/AdsPower Profile 掉登录后发布页是否真的跳到 `/login` 或 `/website-login*`；② 人机验证页在托管 Profile 里的真实 path；③ 真实登录框在发布页的可见性（DOM 补强路径）是否与实机一致。
