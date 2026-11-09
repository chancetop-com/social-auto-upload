# 11 — 托管浏览器 Provider 接缝宽重构（无行为变化）

Status: resolved
Type: task
Blocked by: —（设计 ticket 01–08、10 已 resolved）
Assignee: —

## What to build

把现有 Multilogin 专用的托管分支抽成可扩展的 provider 接缝，为后续 AdsPower 复用，同时保证本地模式与 MLX 的可观察行为不变：

- 新增 `ManagedBrowserProvider` Protocol 与 `ProviderMode`；MLX 实现 `MultiloginProvider`，`start()` 把端口归一化为 CDP URL。
- `browser_session(managed=...)` 取代 `multilogin=`；`BrowserSession` 增加 `adspower` mode 与 `managed` 属性；probe → start → CDP 重试 → `contexts == 1` → yield → disconnect → shield stop 收敛为唯一生命周期模板。
- `sau_commands/browser.py` 成为 canonical helper（激活、flags、provider 解析、label、login/平台拒绝、登录失效文案）；`sau_commands/multilogin.py` 降为 re-export shim，保留旧符号与 MLX-only 语义。
- 16 个浏览器平台模块迁移到 `resolve_managed_provider` / `reject_managed_*`；bilibili 也迁移到 `reject_managed_*`，修复 AdsPower 下静默回退本地的缺口。
- 28 处 `session.mode == "multilogin"` 改为 `session.managed`（含 insgraph 两处单引号）。
- 仅按 spec §11.2 允许的范围调整既有测试；默认套件全绿。

## Acceptance criteria

- [ ] `ADSPOWER_API_KEY` 未设置时，本地与 MLX 的参数解析、默认值、退出码、日志与消息保持原样。
- [ ] 全部 36 个 `browser_session` 调用点使用 `managed=`，无 `multilogin=` 残留。
- [ ] `uploader/` 与 `sau_commands/` 中不存在 `session.mode == "multilogin"`（单双引号均算）。
- [ ] `bilibili login/check/upload-video` 在托管模式下走 `reject_managed_*`，不再依赖 MLX-only 判定。
- [ ] `python -m unittest discover -s tests` 通过（既有环境性失败除外，仍需与基线逐项一致）。
- [ ] `docs/CLI.md` 与 README 的 MLX 行为描述无需因本 ticket 修改。

## Context

- 规格：`.scratch/adspower-browser-mode/spec.md` §5、§12 阶段 1、§11.2。
- 迁移清单与调用点：`.scratch/adspower-browser-mode/research/07-platform-inventory.md` §2–§8。
- 设计裁决：ticket 03（provider 接缝）、ticket 05（测试策略）、ticket 07（逐平台清单）。

## Answer

已实现并合并（merge `0d677cc`）。新增 `ManagedBrowserProvider` Protocol 与 `MultiloginProvider`，`browser_session(managed=)` / `BrowserSession.managed` 收敛唯一生命周期模板，`sau_commands/browser.py` 成为 canonical helper、`multilogin.py` 降为 shim；36 个会话调用点与 28 处 `session.mode` 判定迁移完成。全量套件与基线一致（6 个既有失败），静态守卫通过。
