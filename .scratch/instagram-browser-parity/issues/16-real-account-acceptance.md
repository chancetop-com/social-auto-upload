# 16 — 真实账号真发验收（非阻塞）

Status: ready-for-human
Type: task
Blocked by: 15
规格依据: spec.md §8

## What to build

用真实可发帖账号执行第一波 4 项的真发验收，确认“点击发布前的页面状态”确实落到最终帖子上。此工单明确**不阻塞合并与发布**；未完成前，文档只能写 `offline-verified / post-publish unverified`。

## Acceptance criteria

- [ ] 前置：`sau instagram check` 通过；准备单图、2 图轮播、≤60s MP4；界面至少覆盖 English，条件允许时用中文 UI 复跑。
- [ ] location：`upload-note --location "<已知地点>"` 发布后帖子显示该地点，结果 `options.location.status=set`。
- [ ] alt text：2 图轮播各填一条，发布后编辑页逐张回读与输入一致，顺序正确。
- [ ] 关闭评论：`--no-comments` 发布后评论区确实关闭。
- [ ] AI 标识：`--ai-generated` 发布后帖子显示 AI 标识。
- [ ] 负向：不存在的地点退出 `1` 且主页无新帖；alt-text 条数不符退出 `2` 且浏览器未启动。
- [ ] 结论、时间、帖子 URL 写入 `research/08-acceptance-evidence.md`（进 Git）；截图/录屏放仓库外，只引用路径与时间。
- [ ] 不记录账号名、Cookie、Profile ID。
- [ ] 验完用 `sau instagram delete` 删帖；删除结果未知时先 `verify`，不重删。
- [ ] 全部通过后，才把文档中的 `post-publish unverified` 改为已验证；任一项失败则记录现象并保持未验收状态。

## Comments

- 2026-11-10：由 `spec.md` 拆分；HITL，需真实账号，非阻塞。
