# 06 — 生命周期与所有权（本地 / 云端两套）

Status: open
Type: grilling
Blocked by: 05
Assignee: —

## Question

定义 GoLogin 会话的取得与交还，覆盖两种运行时：

1. **所有权**
   - 「谁启动谁停止」在本地与云端是否同一套；已在运行的 Profile 是 attach、拒绝还是 stop 后重启。
   - start 失败不 stop；start 2xx 但响应坏时是否 best-effort stop（沿用 `StartIncompleteError`）。
2. **连接**
   - CDP 连接超时与重试次数是否沿用 3 × 10s / 退避 2s→4s；云端高延迟是否需要单独预算。
   - `contexts` 必须恰好 1 个的断言在 GoLogin 下是否成立；不成立时的降级策略。
   - 断开用 `browser.close()` 是否只断 CDP、不销毁云端会话；云端会话是否必须显式 stop 才计费结束。
3. **停止**
   - 本地 stop 与云端 stop 的端点、幂等性、已停止时的响应。
   - stop 失败只 warning 的既有策略是否保留；云端 stop 失败是否要额外提示「可能仍在计费」。
   - 取消路径（Ctrl-C / CancelledError）下 shield stop 是否仍适用。
4. **超时与资源**
   - 云端会话的最长寿命、空闲回收、心跳要求；是否需要在上传期间保活。
   - 大文件上传/视频转码在云端运行时是否受会话寿命限制。

## Context

- 现有生命周期模板见 `utils/browser_session.py::_managed_session`。
- 结论要能写成 spec 的时序图与「失败边界」表。
