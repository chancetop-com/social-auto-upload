# 14 — Alt text 端到端

Status: resolved
Type: task
Blocked by: 10
规格依据: spec.md §3.1、§3.3、§4.2、§4.3.2、§5、§7.2–§7.4

## What to build

`upload-note` 支持可重复 `--alt-text`。单图或轮播按图片顺序逐张填写替代文字，关闭无障碍模态框后重新打开回读；数量不符或回读不一致都不发布。

## Acceptance criteria

- [x] `--alt-text` 只注册在 `upload-note`；可重复；未传为 `None`，不触碰页面。
- [x] 条数必须为 0 或等于图片张数 N，否则浏览器启动前退出 `2`。
- [x] 每条去空白后长度必须在 `1..1000`，空串或超长退出 `2`，不截断。
- [x] 打开配文页 `Accessibility` 模态框，断言 `Alt text` 输入框数量等于 N。
- [x] 输入框数量为 0 → `unsupported` + `entry_missing`，退出 `1`；数量为 1..N-1 → `mismatch`，退出 `1`。
- [x] 按 `--images` 顺序逐张填写，关闭模态框后重新打开回读，按顺序严格比较。
- [x] 回读一致记 `set`；不一致或无法重新打开 / 无法关闭 → `mismatch`，退出 `1`。
- [x] 选项失败不点 Share；结果文件记录 alt_text 的 requested / applied / status / reason。
- [x] fake 控制件覆盖单图 1 条、轮播 N 条、顺序错位、数量不符、回读不一致；真实 DOM 验模态框填写与重开回读。
- [x] 视频命令不暴露该参数；文档留到 15。

## Comments

- 2026-11-10：由 `spec.md` 拆分。
- 2026-11-10：已实现并合入 `feat/instagram-parity`（`6673685`，合并 `fb4a9ac`）。`controls/alt_text.py` 打开 Accessibility 模态框、按 `--images` 顺序逐张填写、关闭后重开回读；输入框数量 0 → `unsupported(entry_missing)`，1..N-1 → `mismatch` 并保留部分回读列表。A/B/C 共 54 例全绿。
