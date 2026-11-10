# 14 — Alt text 端到端

Status: ready-for-agent
Type: task
Blocked by: 10
规格依据: spec.md §3.1、§3.3、§4.2、§4.3.2、§5、§7.2–§7.4

## What to build

`upload-note` 支持可重复 `--alt-text`。单图或轮播按图片顺序逐张填写替代文字，关闭无障碍模态框后重新打开回读；数量不符或回读不一致都不发布。

## Acceptance criteria

- [ ] `--alt-text` 只注册在 `upload-note`；可重复；未传为 `None`，不触碰页面。
- [ ] 条数必须为 0 或等于图片张数 N，否则浏览器启动前退出 `2`。
- [ ] 每条去空白后长度必须在 `1..1000`，空串或超长退出 `2`，不截断。
- [ ] 打开配文页 `Accessibility` 模态框，断言 `Alt text` 输入框数量等于 N。
- [ ] 输入框数量为 0 → `unsupported` + `entry_missing`，退出 `1`；数量为 1..N-1 → `mismatch`，退出 `1`。
- [ ] 按 `--images` 顺序逐张填写，关闭模态框后重新打开回读，按顺序严格比较。
- [ ] 回读一致记 `set`；不一致或无法重新打开 / 无法关闭 → `mismatch`，退出 `1`。
- [ ] 选项失败不点 Share；结果文件记录 alt_text 的 requested / applied / status / reason。
- [ ] fake 控制件覆盖单图 1 条、轮播 N 条、顺序错位、数量不符、回读不一致；真实 DOM 验模态框填写与重开回读。
- [ ] 视频命令不暴露该参数；文档留到 15。

## Comments

- 2026-11-10：由 `spec.md` 拆分。
