# 05 — 真实账号 `--no-publish` 协作者验收

**What to build:** 用已登录的本地 Instagram Profile，在图文/轮播与 Reels 各跑一次真实的 `--no-publish` 命令：1–5 个协作者、停在 Share 前、结果为 `prepared`，逐个回读通过。记录账号别名、界面语言、帖型、请求/已选列表与停止点。若运行中登录失效，停止并报告 `blocked: login required`，不自行登录，不把登录问题当成代码失败。不要求第二账号接受邀请。

**Blocked by:** 01 — 图文/轮播：邀请 1–5 个协作者并逐个回读 chip；02 — Reels：在同一面板勾选协作者并逐个回读 checkbox；03 — 协作者的失败与边界语义（两帖型）。

**Status:** ready-for-agent

**Resolution:** completed

- [x] 图文/轮播与 Reels 各完成一次 `--no-publish`，结果为 `prepared`，`options.collaborators.status=set`，`applied` 与请求一致。
- [x] Share 点击为零；未发出任何邀请。
- [x] 记录账号别名、界面语言、帖型、请求/已选列表与停止点，作为验收证据。
- [x] 覆盖至少一个 1 人请求和一个多人（2–5 人）请求；两帖型都能逐个回读。
- [x] 登录失效时明确报告 `blocked: login required`，不尝试自动登录，不把该情况记为代码失败。
- [x] 不要求第二账号接受邀请；接受状态不影响本次验收结论。

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

### 2026-11-24 16:33–16:37 — 修复后复测（通过）

- 前置失败原因：`controls/collaborators.py::_ROWS_JS` 以 `el.closest('[role="dialog"]')` 限定扫描范围，只看到 `Create new post` 创建弹窗，漏掉作为兄弟 `role="dialog"` 的候选浮层，导致候选已渲染仍报 `no_candidates`。
- 修复提交：`dcd1b31 fix(instagram): find collaborator panel in sibling dialog`（集成分支 tip `706fbca`）；已 `git merge feat/instagram-collaborators` 到本验收分支，保留此前失败记录 `f657c52`。
- 账号别名：`luke`（`lukechen918`），Profile：`browser_profiles/chrome/instagram/luke`。
- 登录检查：`sau instagram check --account luke` → `valid`，退出码 `0`，未登录。
- 界面语言：`en`（沿用同一 Profile 当天的只读 `document.documentElement.lang=en` 探测；`navigator.language=en`）。
- 真实公开账号取自既有证据：`natgeo`、`natgeotravel`、`natgeobooks`；全部一次选中，无替换、无账号不合格。
- 所有运行均为 `--no-publish`，`status=prepared`，`options.collaborators.status=set`，`applied == requested` 且顺序一致；退出码均为 `0`。

| # | 帖型 | 请求 / 已选 | 结果文件 | 停止点 | 结果 |
|---|---|---|---|---|---|
| 1 | 图文/轮播（1 张） | `["natgeo"]` / `["natgeo"]` | `.local/acceptance/instagram-collaborators/after-fix/note-1.json` | Share 前，`--no-publish` 就绪点 | 通过 |
| 2 | 图文/轮播（3 张） | `["natgeo","natgeotravel","natgeobooks"]` / 同序 | `.local/acceptance/instagram-collaborators/after-fix/note-3.json` | Share 前，`--no-publish` 就绪点 | 通过 |
| 3 | Reels | `["natgeo"]` / `["natgeo"]` | `.local/acceptance/instagram-collaborators/after-fix/reel-1.json` | Share 前，`--no-publish` 就绪点 | 通过 |
| 4 | Reels | `["natgeo","natgeotravel","natgeobooks"]` / 同序 | `.local/acceptance/instagram-collaborators/after-fix/reel-3.json` | Share 前，`--no-publish` 就绪点 | 通过 |

- Share 零点击证据：四条日志均含 `Instagram 发布就绪，--no-publish 停在 Share 前（未点击发布）`（`note-1.log` 16:34:17、`note-3.log` 16:35:13、`reel-1.log` 16:36:08、`reel-3.log` 16:37:04）；结果均为 `prepared`，无 `content_id` / `post_id` / `post_url`，未发布、未发出邀请。
- stdout 与结果文件一致性：四条运行均解析 stdout JSON 并与 `--result` 文件逐字段比较，全部相等（包括 `prepared`、五个 `options` 键与协作者顺序）。
- 代表性结果（`note-3.json`，stdout 与文件相同）：

```json
{
  "platform": "instagram",
  "title": "验收：图文协作者 3 人（修复后）",
  "status": "prepared",
  "options": {
    "location": {"requested": null, "applied": null, "status": "not_requested"},
    "alt_text": {"requested": null, "applied": null, "status": "not_requested"},
    "comments": {"requested": null, "applied": null, "status": "not_requested"},
    "ai_generated": {"requested": null, "applied": null, "status": "not_requested"},
    "collaborators": {
      "requested": ["natgeo", "natgeotravel", "natgeobooks"],
      "applied": ["natgeo", "natgeotravel", "natgeobooks"],
      "status": "set"
    }
  },
  "topics": []
}
```

- 复测结论：**通过**。验收条件（两帖型、1 人与多人、逐项回读、Share 前停止）均满足；未发现残余 DOM/行为问题。`Resolution: completed` 未设置，交由编排方处理。

### 2026-11-24 — 关闭

- 代码审查修复（含面板识别、失败映射与 applied 前缀）已合并；验收通过后由编排方标记 `Resolution: completed`。

### 2026-11-24 — 有头图文回归与修复

22:57 和 22:59 的真实账号图文干跑均在输入用户名之前退出 `1`，结果为 `mismatch/list_not_collapsed`、`applied=null`。两个现场的兄弟弹窗均已显示与入口同名的说明图标，尚无候选行或 Done。

修复后的本地受控页面已使用系统 Chrome 可见窗口和 `HUMANIZE=1` 验证。图文运行退出 `0`，结果为 `prepared`、`collaborators.status=set`、`applied=["natgeo"]`，页面记录 Share 点击数为零。

### 2026-11-24 23:27–23:28 — 单人和三人真实账号复验通过

在修复提交 `cf6419a` 上，使用已登录的本地 `luke` Profile、系统 Chrome 可见窗口和 `HUMANIZE=1`，分别执行两次 `instagram upload-note --headed --no-publish`。两次均上传一张 `videos/demo1.png`。

| Share 前停止时间（北京时间） | 请求顺序 | 实际回读顺序（`applied`） | 本地结果文件 |
|---|---|---|---|
| 23:27:49 | `natgeo` | `natgeo` | `single.json` |
| 23:28:38 | `natgeo`、`natgeotravel`、`natgeobooks` | `natgeo`、`natgeotravel`、`natgeobooks` | `multiple.json` |

两次均退出 `0`，结果为 `status=prepared`、`options.collaborators.status=set`。stdout JSON 与各自的结果文件逐字段一致。两份日志都记录了在 Share 前停止，帖子和协作者邀请均未发出。结果文件保存在集成工作树的 `.local/instagram-results/2026-11-24-headed-collaborators/`。
