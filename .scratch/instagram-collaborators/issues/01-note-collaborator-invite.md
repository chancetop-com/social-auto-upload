# 01 — 图文/轮播：邀请 1–5 个协作者并逐个回读 chip

**What to build:** 作者可以在 `sau instagram upload-note` 上重复传 `--collaborator USERNAME`（1–5 个）。命令在点击 Share 前打开创建页的 Collaborators 面板，按 username 精确匹配并逐个选中；每选中一个，就在预览图上回读该 username 的协作者标签（chip），确认后再处理下一个。全部完成后点 Done 收起面板。结果写入既有 `options` 的 `collaborators` 记录；`--no-publish` 停在 Share 前并输出 `prepared`。空值、重复、超过 5 个在启动浏览器前退出 `2`；无候选、无同 username、点击或回读失败在 Share 前退出 `1`。

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

**Resolution:** completed

- [x] `upload-note --collaborator alice --collaborator bob --no-publish` 停在 Share 前，结果为 `prepared`，`options.collaborators.status=set`，`applied` 按请求顺序为 `[alice, bob]`；Share 点击为零。
- [x] 1 个和 5 个协作者都能完成；传入第 6 个时在启动浏览器前退出 `2`，不启动浏览器。
- [x] `alice`、`@alice`、`Alice` 归一化为同一个请求；空值与规范化后的重复在启动浏览器前退出 `2`。
- [x] 请求 `nike` 时只选 username 为 `nike` 的候选，不选 `_nikeza5`；无候选或无同 username 时退出 `1`，Share 点击为零。
- [x] Done 收起面板后流程继续到 Share 就绪；已选协作者在停止点仍可见于预览图。
- [x] 未传 `--collaborator` 时行为、结果字段与退出码与现状一致；`options` 固定包含 `collaborators` 键，值为 `not_requested`。
- [x] 结果文件、stdout 与 `--result PATH` 三处内容一致。
- [x] CLI 边界与受控页面回归覆盖中英文入口、1–5 人、精确匹配与 Share 零点击。
