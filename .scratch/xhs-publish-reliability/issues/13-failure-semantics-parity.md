# 13 — 本地/托管失败语义统一

Status: open
Type: grilling
Blocked by: 03
Assignee: —

## Question

同一种失败在两种模式下给出不同出口，调度侧无法写出统一规则。需要确认：

1. **登录失效退出码**：本地现为 `RuntimeError` → exit 1（`sau_commands/xiaohongshu.py:313-317`），托管为 `LoginRequiredError` → exit 10。统一为 10？
2. **错误文案**：`main.py:116-119` 硬编码“请在 Multilogin 应用中登录”，AdsPower 用户会被指错 App；是否改用 `login_required_error()` / `managed_app_label()`（`sau_commands/browser.py:273-284`）。
3. **参数命名**：`_raise_if_login_required(..., multilogin=True)` 实为“任何托管模式”（`session.managed`，含 AdsPower）。是否改名并补测试。
4. **判定标准漂移**：`check` 的宽松/严格差异是否由 12 统一（交叉引用，不重复决策）。
5. 是否需要一次性的“退出码契约表”作为 spec 的一部分（0/1/2/9/10/11 与各失败类型映射）。

产出：错误类型 × 模式 × 退出码 三维表 + 文案规范 + 需要改的调用点清单。
