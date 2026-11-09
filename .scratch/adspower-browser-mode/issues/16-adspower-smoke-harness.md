# 16 — Opt-in AdsPower smoke harness（默认 skip）

Status: ready-for-agent
Type: task
Blocked by: 13
Assignee: —

## What to build

提供一个默认跳过、需要真实 AdsPower 桌面应用才能运行的冒烟入口，只验证浏览器生命周期：

- `SAU_ADSPOWER_SMOKE=1` 且 `ADSPOWER_API_KEY` / `ADSPOWER_TEST_PROFILE_ID` 存在时才运行，否则 `unittest.skip`。
- 流程：probe → start（headless）→ `connect_over_cdp(ws)` → 读取当前 URL/title → disconnect → stop。
- 失败诊断脱敏：不含 API key、不含真实账号/Profile 名称；只输出 host:port 与 HTTP/code/msg。
- 不测试 `delete_cache=1`、不上传内容、不改 Profile。
- 执行结果归 ticket 09；本 ticket 只交付 harness。

## Acceptance criteria

- [ ] 默认 `python -m unittest discover -s tests` 中该测试为 skipped，不访问网络、不启动浏览器。
- [ ] 开启 opt-in 后按固定顺序执行并在 finally 中 stop。
- [ ] 失败输出不含 key 或完整 ws 路径。
- [ ] ticket 09 仍保持 `open`，文档注明真实冒烟未执行。

## Context

- 规格：§12 阶段 3、§13.2（未知项）、ticket 09。
- 参考：`tests/test_mlx_smoke.py` 的 opt-in 结构。
