# 05 — 真实账号 `--no-publish` 协作者验收

**What to build:** 用已登录的本地 Instagram Profile，在图文/轮播与 Reels 各跑一次真实的 `--no-publish` 命令：1–5 个协作者、停在 Share 前、结果为 `prepared`，逐个回读通过。记录账号别名、界面语言、帖型、请求/已选列表与停止点。若运行中登录失效，停止并报告 `blocked: login required`，不自行登录，不把登录问题当成代码失败。不要求第二账号接受邀请。

**Blocked by:** 01 — 图文/轮播：邀请 1–5 个协作者并逐个回读 chip；02 — Reels：在同一面板勾选协作者并逐个回读 checkbox；03 — 协作者的失败与边界语义（两帖型）。

**Status:** ready-for-agent

- [ ] 图文/轮播与 Reels 各完成一次 `--no-publish`，结果为 `prepared`，`options.collaborators.status=set`，`applied` 与请求一致。
- [ ] Share 点击为零；未发出任何邀请。
- [ ] 记录账号别名、界面语言、帖型、请求/已选列表与停止点，作为验收证据。
- [ ] 覆盖至少一个 1 人请求和一个多人（2–5 人）请求；两帖型都能逐个回读。
- [ ] 登录失效时明确报告 `blocked: login required`，不尝试自动登录，不把该情况记为代码失败。
- [ ] 不要求第二账号接受邀请；接受状态不影响本次验收结论。

## Comments

### 2026-11-24 15:30–15:37 — 真实账号 `--no-publish` 验收（未通过，非登录阻塞）

- 账号别名：`luke`（`lukechen918`），Profile：`browser_profiles/chrome/instagram/luke`
- 登录检查：`python -m sau_cli instagram check --account luke` → `valid`，退出码 `0`，未触发登录流程。
- 界面语言：`en`。只读探测同一 Profile 的 `document.documentElement.lang` 得 `en`（`navigator.language=en`，`navigator.languages=[en, zh-CN, zh]`；探测文件 `.local/acceptance/instagram-collaborators/language-probe.json`）；每次运行 CLI 日志也记录 `页面语言 html[lang]=en`。
- 所有运行均使用 `--no-publish`，停在 Share 前；`status=not_submitted`、`stage=options`，结果无 `content_id` / `post_id` / `post_url`（未发布），未点击 Share，未发出协作者邀请。
- 运行结果（均为退出码 `1`，`applied=[]`，`status=mismatch`，`reason=no_candidates`）：

| # | 帖型 | 请求的 username | `options.collaborators` | 结果文件 | 停止点 | 结果 |
|---|---|---|---|---|---|---|
| 1 | 图文/轮播（1 张） | `natgeo` | `requested=["natgeo"]`, `applied=[]`, `mismatch/no_candidates` | `.local/acceptance/instagram-collaborators/note-1.json` | `stage=options`，Share 前 | 失败（退出 1） |
| 2 | 图文/轮播（3 张） | `natgeo`, `nasa`, `nike` | `requested=["natgeo","nasa","nike"]`, `applied=[]`, `mismatch/no_candidates` | `.local/acceptance/instagram-collaborators/note-3.json` | `stage=options`，Share 前 | 失败（退出 1） |
| 3 | Reels（1 个协作者） | `natgeo` | `requested=["natgeo"]`, `applied=[]`, `mismatch/no_candidates` | `.local/acceptance/instagram-collaborators/reel-1.json` | `stage=options`，Share 前 | 失败（退出 1） |
| 4 | Reels（3 个协作者） | `natgeo`, `nasa`, `nike` | `requested=["natgeo","nasa","nike"]`, `applied=[]`, `mismatch/no_candidates` | `.local/acceptance/instagram-collaborators/reel-3.json` | `stage=options`，Share 前 | 失败（退出 1） |

- 实际测试账号选择：4 条真实公开账号取自既有证据截图（`natgeo`/`nasa`/`nike` 均出现在 `evidence/02-note-chips-zh.png`、`03-reels-panel-en.png`、`04-reels-reopened-five-en.png`）。
- 全量日志：同目录 `note-1.log`、`note-3.log`、`reel-1.log`、`reel-3.log`。失败页面截图/HTML：`.local/acceptance/instagram-collaborators/evidence/<evidence-id>/page.{png,html}`（原始目录同时保留在 worktree `.local/instagram-errors/`）。

#### 观察到的代码/DOM 问题（未修复）

输入 `natgeo` 后页面**确实渲染了候选**（`natgeo`、`natgeotravel`、`natgeobooks`…，见失败截图），但控件报 `no_candidates`。保存的失败 DOM 显示：候选行/checkbox 位于**第二个** `role="dialog"` 浮层（无 aria-label），而 `creation-collaborator-input` 属于 `aria-label="Create new post"` 的创建弹窗；`controls/collaborators.py::_ROWS_JS` 用 `el.closest('[role="dialog"]')` 限定范围，因此只扫描创建弹窗、看不到候选浮层。四种组合（图文/Reels × 1/3 人）均在同一处、同一用户名 `natgeo` 上失败，非偶发。

精确结果 JSON（`note-1.json`；其余三条仅 `requested` 不同，`status/stage/reason/error` 相同）：

```json
{
  "platform": "instagram",
  "title": "验收：图文协作者 1 人",
  "status": "not_submitted",
  "options": {
    "location": {"requested": null, "applied": null, "status": "not_requested"},
    "alt_text": {"requested": null, "applied": null, "status": "not_requested"},
    "comments": {"requested": null, "applied": null, "status": "not_requested"},
    "ai_generated": {"requested": null, "applied": null, "status": "not_requested"},
    "collaborators": {"requested": ["natgeo"], "applied": [], "status": "mismatch", "reason": "no_candidates"}
  },
  "topics": [],
  "stage": "options",
  "error": "Instagram 发布选项未生效: collaborators=mismatch(no_candidates); collaborators: Instagram 协作者搜索未出现任何候选：请求「natgeo」",
  "evidence_dir": ".local/instagram-errors/fa153f2774f544ee915af8db4caefc23"
}
```

- 验收结论：**未通过**。不是 `blocked: login required`；登录有效。`Resolution: completed` 未设置，交由编排方处理。
