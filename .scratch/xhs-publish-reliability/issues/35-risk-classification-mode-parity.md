# 35 — 风控分类与模式一致性

**What to build:** 本地模式和托管模式用同一个判据识别登录页/人机验证页，都退出 `10`。本地模式不再因为少了一道托管分支就完全看不见登录页；文案按 provider 说对名字（AdsPower 用户不会再被指去 Multilogin）。同时删掉一批随新语义失效的死代码。

**Blocked by:** 33（登录锚点与可见性判定）.

**Status:** ready-for-agent

**分类器判据（唯一一份，只读、不注入脚本）**

- [ ] 只比较 URL 的 path，不读 query、不做 unquote：`/website-login/captcha` → verification；`/website-login`（裸与未知子路径）→ login；`/login` → login；其余 → 无
- [ ] path 未命中时补强：登录框按 `visible` 档可见 → login；path 命中则不查 DOM
- [ ] 不做非跳转式验证码弹层识别；读失败按"不拦截"处理
- [ ] `?redirectPath=/login` 一类 query 不得误判

**模式一致性**

- [ ] 8 处 `if multilogin:` 门全部删除；参数由布尔 `multilogin` 换成三值 `mode`，调用点传会话模式
- [ ] 四句文案在 raise 点拼：本地/托管 × login/verification；`{App}` 取公开的 provider 标签；不带 profile id；本地句只给账号名占位符
- [ ] `publish_attempted=True` 时在上句后追加"发布可能已发出：重跑前请先确认该笔记是否存在。"
- [ ] `reason` 与 `publish_attempted` 字段保留，供测试与日志断言

**检查点**

- [ ] C1：导航到发布页后立刻分类，命中 → `10`（未派发）
- [ ] C2：每个可能超过 2s 的等待循环每轮查一次（视频预览轮询、图文标题等待、ARM 轮询），命中 → `10`（未派发）
- [ ] 检查点抛出的登录失效错误不得被宽 `except Exception` 吞掉

**删除清单**

- [ ] 删除：登录 URL 子串表、`_raise_if_login_required`、发布失败词表与对应异常及其两处 `except`、失败提示扫描、未使用的成功 URL 常量、无调用点的上传错误处理、无调用点的原创声明检查

**验证**

- [ ] **核心回归**：本地模式用坏 cookie 打开发布页 → 判出 login → `10`，且 stderr 不含 `publish_attempted=true`
- [ ] 四文案 × 两模式断言；AdsPower 出现且 Multilogin 不出现
- [ ] `check`/登录链路可先不动（归 37）
