# 12 — AI 生成标识端到端

Status: ready-for-agent
Type: task
Blocked by: 11
规格依据: spec.md §3.1、§4.2、§4.3.4、§5、§7.2–§7.4

## What to build

两个上传命令支持 `--ai-generated` 与 `--no-ai-generated`。显式请求时在配文页操作 `Add AI label` 开关并回读；请求开启但入口缺失就失败，请求关闭且入口缺失视为已满足。

复用 11 建立的开关读写与状态映射，不重复实现。

## Acceptance criteria

- [ ] 两个命令都注册互斥的 `--ai-generated` / `--no-ai-generated`；同传由 argparse 退出 `2`；未传为 `None`。
- [ ] 请求 on + 入口缺失 → `unsupported` + `entry_missing`，退出 `1`，不点 Share。
- [ ] 请求 on + 入口存在但 disabled / 账号不合格 → `unsupported` + `account_ineligible`，退出 `1`。
- [ ] 请求 off + 入口缺失或已 off → `default_off`，退出 `0`。
- [ ] 请求 off + 当前 on → 点击一次 → 回读 false 记 `set`；回读仍 true 或读回失败 → `mismatch`，退出 `1`。
- [ ] 请求 on + 当前已 on → 记 `set`，不点击。
- [ ] 开关状态按 `aria-checked` 读取；AI 与关闭评论是两个独立开关，无互斥。
- [ ] 结果文件记录 `ai_generated` 的 requested / applied / status / reason。
- [ ] fake 层覆盖 set→回读一致、不一致、on 缺失、off 已满足、未传零交互；真实 DOM 验 happy path。
- [ ] 不引入 `--aigc` 别名；文档留到 15。

## Comments

- 2026-11-10：由 `spec.md` 拆分。
