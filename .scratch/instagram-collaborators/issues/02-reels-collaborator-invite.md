# 02 — Reels：在同一面板勾选协作者并逐个回读 checkbox

**What to build:** 作者可以在 `sau instagram upload-video` 上使用同一组 `--collaborator USERNAME`。命令打开 Reels 配文页的 Collaborators 面板，按 username 精确匹配并逐个勾选；每勾选一个，就回读该行的 checkbox 选中状态，确认后再处理下一个。全部完成后点 Done 收起面板。结果与图文一致；不回归图文路径。Reels 没有预览图 chip，已选只在面板内可读，因此必须逐个回读。

**Blocked by:** 01 — 图文/轮播：邀请 1–5 个协作者并逐个回读 chip。

**Status:** ready-for-agent

**Resolution:** completed

- [x] `upload-video --collaborator alice --collaborator bob --no-publish` 停在 Share 前，结果为 `prepared`，`options.collaborators.status=set`，`applied` 按请求顺序为 `[alice, bob]`；Share 点击为零。
- [x] 1 个和 5 个协作者都能完成；传入第 6 个时在启动浏览器前退出 `2`，不启动浏览器。
- [x] 每个 username 选中后，面板行 checkbox 读到选中状态；点击后未选中时退出 `1`，Share 点击为零。
- [x] Done 收起面板，已选保留；面板收起后流程继续到 Share 就绪。
- [x] 请求 `nike` 时只选 username 为 `nike` 的候选，不选 `_nikeza5`；无候选或无同 username 时退出 `1`。
- [x] Reels 的结果字段、退出码与错误文案和 01 保持一致；`upload-note` 行为不变。
- [x] 结果文件、stdout 与 `--result PATH` 三处内容一致。
- [x] Reels 的受控页面回归覆盖中英文入口、1–5 人、checkbox 回读与 Done 收起。
