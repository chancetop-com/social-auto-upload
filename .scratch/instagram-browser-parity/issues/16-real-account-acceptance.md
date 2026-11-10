# 16 — 真实账号真发验收（非阻塞）

Status: resolved
Type: task
Blocked by: 15
规格依据: spec.md §8

## What to build

用真实可发帖账号执行第一波 4 项的真发验收，确认“点击发布前的页面状态”确实落到最终帖子上。此工单明确**不阻塞合并与发布**；未完成前，文档只能写 `offline-verified / post-publish unverified`。

## Acceptance criteria

- [x] 前置：`sau instagram check` 通过；准备单图、2 图轮播、≤60s MP4；界面至少覆盖 English，条件允许时用中文 UI 复跑。
- [x] location：`upload-note --location "<已知地点>"` 发布后帖子显示该地点，结果 `options.location.status=set`。
- [x] alt text：2 图轮播各填一条，发布后编辑页逐张回读与输入一致，顺序正确。
- [x] 关闭评论：`--no-comments` 发布后评论区确实关闭。
- [x] AI 标识：`--ai-generated` 发布后帖子显示 AI 标识。
- [x] 负向：不存在的地点退出 `1` 且主页无新帖；alt-text 条数不符退出 `2` 且浏览器未启动。
- [x] 结论、时间、帖子 URL 写入 `research/08-acceptance-evidence.md`（进 Git）；截图/录屏放仓库外，只引用路径与时间。
- [x] 不记录账号名、Cookie、Profile ID。
- [x] 验完用 `sau instagram delete` 删帖；删除结果未知时先 `verify`，不重删。
- [x] 全部通过后，才把文档中的 `post-publish unverified` 改为已验证；任一项失败则记录现象并保持未验收状态。

## Comments

- 2026-11-10：由 `spec.md` 拆分；HITL，需真实账号，非阻塞。

## Comments

- 2026-11-10：真发验收完成（English UI、Personal、本地 cookie）。证据见 [`research/08-acceptance-evidence.md`](../research/08-acceptance-evidence.md)：一条两图轮播同时覆盖四项，发布前 `options` 全 `set`，发布后地点 / `img[alt]` / `AI content` / 无评论输入框均回读一致；负向两条（地点不存在 exit 1、alt 条数不符 exit 2）符合预期；帖子已 `delete` 并返回 `did_delete=true`。验收中暴露并修复了 6 个真机问题（英文固定、三个控件选择器、通知弹窗遮挡、删帖菜单项漂移）。中文界面、专业账号、托管模式与 `upload-video` 组合仍未覆盖。
