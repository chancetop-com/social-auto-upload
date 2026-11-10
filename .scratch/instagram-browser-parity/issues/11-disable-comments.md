# 11 — 关闭评论端到端

Status: resolved
Type: task
Blocked by: 10
规格依据: spec.md §3.1、§4.2–§4.3.3、§5、§7.2–§7.4

## What to build

两个上传命令支持 `--no-comments`。显式请求关闭时，在点 Share 前展开高级设置并操作 `Turn off commenting`，回读确认后发布。

入口缺失或账号不可用时按“已关闭”处理，不把用户卡死；主动关闭失败则整单不发布。本工单同时建立后续 AI 开关可复用的读写与回读模式。

## Acceptance criteria

- [x] `upload-video` 与 `upload-note` 都注册 `--no-comments`；未传为 `None`，不触碰页面。
- [x] 显式 off + 入口缺失 → `default_off` + `entry_missing`，退出 `0`。
- [x] 入口存在且已 off → `default_off`，不点击，退出 `0`。
- [x] 控件 disabled 但已 off → `default_off`，不点击，退出 `0`。
- [x] 当前 on → 点击一次 → 回读 `comments_enabled=false` 记 `set`；点击后仍 on 或回读失败 → `mismatch`，退出 `1`。
- [x] 开关按“checked = 评论已关闭”反转读取，不把原始 `aria-checked` 直接当“评论开启”。
- [x] 高级设置展开幂等，重复调用只展开一次。
- [x] 选项失败不点 Share，退出 `1`；结果文件含 `options`，失败证据落盘。
- [x] fake 控制件覆盖 set→回读、回读不一致、入口缺失、已 off、disabled 已满足、未传零交互、重复展开。
- [x] 真实 DOM 只验 happy path：展开 → 开关 → 回读。
- [x] 不修改 `verify` / `delete` / `login` / `check`；文档留到 15。

## Comments

- 2026-11-10：由 `spec.md` 拆分。
- 2026-11-10：已实现并合入 `feat/instagram-parity`（`d2c91be`，合并 `5bbeff0`）。`controls/toggles.py` 提供可复用的 `SwitchControl` + `disclosure_panel`；comments 以 `invert=True` 反转读取，Advanced settings 展开幂等；入口缺失/disabled 且请求关闭均记 `default_off`。A/B/C 共 54 例全绿。
