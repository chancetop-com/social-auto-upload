# 36 — 提交语义：ARM → FIRE → OBSERVE

**What to build:** 把"点一次发布"变成机器可证明的三段：就绪前只观察不点，派发最多一次，派发后只认 URL 判断结果。任何 `1` 都意味着确定没发；任何"可能已发"只能是 `9` 或 `10 + publish_attempted=true`。`--no-publish` 升级为"跑到 ARM 就绪"，于是干跑真的能证明"只差点一下"。

**Blocked by:** 31（预算）、33（发布按钮锚点）、34（点击接口与按下前后判定）、35（分类器与文案）.

Status: resolved

**ARM（唯一就绪谓词，上传完成票复用）**

- [x] 四个条件全满足才算就绪：发布按钮存在；按 `interactive` 档可用（含 disabled / pointer-events / 落点）；`is-publish != "false"`（缺失视为通过）；`submit-disabled != "true"`（缺失视为通过）
- [x] 每轮**重新解析**，不缓存 locator；新版存在但禁用时**不回落**旧版
- [x] 1s 轮询；窗口 `min(60s, 剩余预算)`；用尽 → `1`（确定未发布）
- [x] ARM 轮内命中登录/验证 → `10`，`publish_attempted=False`
- [x] 定时发布复用同一元素（只变文案），不按策略换按钮

**FIRE**

- [x] 先置位 `publish_clicked = True`，再派发
- [x] 派发前顺序：提交前停顿 → 落点复核 → 人类化点击
- [x] 同一次运行**恰好一次** `mouse.down`；派发后无论抛什么，**不再触碰按钮**
- [x] 按下之前任何异常 = 确定未派发；按下之后任何异常 = 可能已派发 → `9`
- [x] 派发后异常且页面已是登录/验证 → `10` + `publish_attempted=true`

**OBSERVE**

- [x] 500ms 轮询，窗口 `min(15s, 剩余预算)`
- [x] 判据只认 URL：path 不含 `/publish/publish` 且分类器为无 → `0`
- [x] 窗口内落登录/验证页 → `10` + `publish_attempted=true`
- [x] 15s 到点仍在 `/publish/publish` → `9`；预算先耗尽 → `9`
- [x] C4 与 URL 判定同一循环；分类命中优先于"仍在页面上 → 9"；命中绝不把 `0` 抬成 `10`
- [x] **零文案扫描**：限流/拒绝/toast 三张词表为空，不再有扫描调用

**检查点与调用方契约**

- [x] C3：`--not-before` 等待之后、进 ARM 之前必查，命中 → `10`（未派发）
- [x] `publish_attempted` 一律现取 `publish_clicked` 变量，不按调用点硬编码
- [x] 仅当"派发后"检出登录/验证时，退出 `10` 额外向 stderr 打**单独一行** `publish_attempted=true`（固定 token、无前缀、无时间戳）；点击前的 `10` 不打
- [x] 退出码镜像新增本票各行（`0`/`1`/`9`/`10` 前后两态）

**`--no-publish`（干跑）**

- [x] 跑到 ARM 就绪 → 打一条日志 → `0`，不进入 FIRE
- [x] 干跑**跳过** `--not-before` 等待，但**仍执行** C1/C2/C3 与定时回读
- [x] ARM 未就绪 → `1`（预期信号，不是缺陷）

**测试**

- [x] 四条件逐个不满足 → 继续等；满足 → 恰好 1 次按下
- [x] FIRE 抛错 → `9` 且零二次点击；ARM 用尽 → `1`；离开且非登录页 → `0`；15s 未离开 → `9`
- [x] 断言无 toast 扫描调用、无关键词常量

## Comments

- ARM：`_arm_ready(page, *, budget) -> (bool, reason)` 是唯一就绪谓词。每轮重新 `page.locator("xhs-publish-btn")`；`utils.dom.check(..., "interactive", point=(0.65, 0.5))` 覆盖存在/唯一/disabled/pointer-events/hit-test，再读 `is-publish != "false"`、`submit-disabled != "true"`（缺失或读失败视为通过）。只有新版选择器，无旧版回落。
- ARM 驱动：`_wait_for_arm(page, *, budget, mode, publish_clicked) -> None`。1s 轮询，窗口 `min(60s, 剩余预算)`；每轮先 C2 分类（命中 → `10`，`publish_attempted=False`），再 `budget.check_pre_click()`，最后谓词。窗口/预算用尽 → `budget.pre_click_error()`（`1`，确定未发布），不再空转。
- FIRE：`_fire_publish(page, *, budget, humanizer, mode) -> None`。顺序 = `before_submit()` → 预算复核 → 重新解析/落点复核 → `humanizer.click(..., point=(0.65, 0.5))`；置位 `publish_clicked = True` 在 `mouse.down` 之前。全程只调用一次点击接口，派发后不再触碰按钮。`mouse.down` 前异常原样上抛（`1`）；`exc.click_dispatched == "maybe"` 后异常只分类一次：登录/验证命中 → `LoginRequiredError(..., publish_attempted=True)`（`10`），否则 `budget.timeout_error(True)`（`9`）。
- OBSERVE：`_observe_publish(page, *, budget, publish_clicked, mode) -> None`。500ms 轮询，窗口 `min(15s, 剩余预算)`；每轮先 C4 分类（命中 → `10` + `publish_attempted=True`），再只看 `urlsplit(page.url).path`：不含 `/publish/publish` → 成功返回（`0` 语义）。URL 读失败按仍在页面上处理，窗口/预算用尽 → `timeout_error(True)`（`9`）。零文案扫描。
- C3：两个入口都在 `wait_until_allowed(...)` 之后、`_wait_for_arm(...)` 之前调用 `_check_blocked(page, mode, publish_attempted=publish_clicked)`；命中 → `10`（未派发）。
- `publish_attempted` 现取：C1/C2/C3 与 ARM 都用入口里的 `publish_clicked` 变量；FIRE 用 `mouse.down` 前刚置位的局部变量；OBSERVE 用入口在 FIRE 成功后置位的同一变量。没有按调用点硬编码。
- `--no-publish`：跳过 `wait_until_allowed`，但仍执行 C1/C2/C3 与定时回读；跑到 ARM 就绪打一条 `ARM 就绪，--no-publish 停在发布按钮前（未点击发布）` 后返回 0，不进入 FIRE；ARM 未就绪 → `1`。
- stderr：`sau_cli.main` 捕获 `LoginRequiredError` 后，仅当 `publish_attempted` 为真再打一行固定 `publish_attempted=true`（无前缀/时间戳）；点击前的 `10` 不打。
- 退出码镜像：`tests/test_xhs_exit_contract.py` 新增 `verification-before-dispatch`、`login-after-dispatch`、`verification-after-dispatch`、`arm-window-exhausted` 四行（后两者断言 stderr 行）；`PENDING` 只剩 `topic-mismatch`（39）与 `metadata-failure`（40），`covered | PENDING == FULL_SET` 仍成立。
- 测试：`tests/test_xhs_submit.py` 35 条（ARM 四条件、每轮重解析、窗口 60s/预算 3s 用尽、ARM 内 C2、FIRE 恰一次 `mouse.down`、派发前/后异常 1/9/10、OBSERVE 15s/预算/C4 优先、URL 读失败不判成功、`--no-publish` 跳过 `--not-before`、C3 在 ARM 前、零文案扫描）。既有 XHS 预算/上传/分类用例补齐发布按钮脚本，`_wait_publish_outcome` 用例改为 `_observe_publish`。
- 全量：`python -m unittest discover -s tests -t .` → 1320 tests OK（skipped=2）。
- 真机项：`未验证（无真机环境）` —— ① 真实发布按钮在 `is-publish` / `submit-disabled` 上的取值时机；② 60s 就绪窗与 15s 观察窗在实机抖动下的余量；③ `--no-publish` 停在按钮前的日志与真实页面状态；④ 派发后异常时页面是否已跳登录/验证页。
