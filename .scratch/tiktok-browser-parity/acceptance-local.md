# TikTok ticket 19 — 本地模式真实验收记录

- 日期：2026-11-06
- 账号：`lukechen`（私有账号）
- 模式：本地 cookie 模式（未设置 `MLX_API_TOKEN`）
- 浏览器：Patchright 自带 Chromium，`locale=en-US`，`--headed`
- Cookie：`cookies/tiktok_lukechen.json`
- 说明：公开账号专属项（无参数公开发布、`--privacy public` 正向、公开账号首项文案）因账号类型不满足，标记为“条件未满足/未验证”。

## 预检

| 项 | 结果 | 证据 |
| --- | --- | --- |
| 本地登录 | 成功保存 cookie | `.venv/bin/sau tiktok login --account lukechen`；`cookies/tiktok_lukechen.json` |
| `check`（无头） | `valid` / `0` | 14:39 |
| `check`（有头，中文界面问题修复后） | `valid` / `0` | 14:51；`data-e2e=select_video_button` + `locale=en-US` |

## 负向用例

| 用例 | 期望 | 实际 | 证据 |
| --- | --- | --- | --- |
| 私有账号请求 `--privacy public` | 严格失败，退出 `1`，不发布 | 退出 `1`；请求 `public`，实际 `Followers`；浮层已关闭 | `.local/tiktok19/public-negative-v2.log` |
| `--branded-content --privacy only-me` | 本地校验失败，退出 `2`，不启动浏览器 | 退出 `2`，argparse 前业务校验；未启动浏览器 | `.local/tiktok19/brand-onlyme-negative.log` |

## 正向发布

| 用例 | 参数 | 退出码 | 帖子 ID / URL | 页面/帖子核对 |
| --- | --- | --- | --- | --- |
| 公开账号无新参数 | 无新 flag | `0` | `https://www.tiktok.com/@lukechen95/video/7704974050090683661` | Content 行 **Everyone**；真实触发 `Post now` 兜底 |
| 公开账号 `--privacy public` | `--privacy public` | `0` | `https://www.tiktok.com/@lukechen95/video/7704974226096246029` | Content 行 **Everyone**；真实触发 `Post now` 兜底 |
| 公开账号 `--privacy followers` | `--privacy followers` | `1` | — | 严格失败：requested `followers` / actual `Everyone`（公开账号无 Followers 选项） |
| 公开账号图片帖选项 | `upload-note ... --privacy public --no-comments --aigc --your-brand` | `0` | `https://www.tiktok.com/@lukechen95/video/7704976028485176590` | Content 行 **Everyone**；帖子页 **Promotional content** + **Creator labeled as AI-generated**；Description/tags 正确 |
| only-me 基线 v3 | `--privacy only-me` | `0` | `https://www.tiktok.com/@lukechen95/video/7704949738667298062` | Content 列表显示 **Only me**；标题残留旧文案 “emo”，已用 `ControlOrMeta+A` 修复，v4 复验 |
| only-me 基线 v4 | `--privacy only-me` | `0` | `https://www.tiktok.com/@lukechen95/video/7704950472880229645` | 干净标题；read_result 返回 ID；only-me 隐私路径复验 |
| 隐私 followers | `--privacy followers` | `0` | `https://www.tiktok.com/@lukechen95/video/7704950885151018254` | CLI 回读 Followers；Scheduled 列表同账号 Followers 行确认；Web 帖子页不显示 Followers 标签 |
| 隐私 friends | `--privacy friends` | `0` | `https://www.tiktok.com/@lukechen95/video/7704951141179641102` | 帖子页 **Friends only**；Content 行 **Friends** |
| 互动/复用/AIGC/品牌组合 | `--privacy only-me --no-comments --disable-reuse --aigc --your-brand` | `0` | `https://www.tiktok.com/@lukechen95/video/7704956309300382989` | 帖子页 **Private** + **Promotional content** + **Creator labeled as AI-generated**；Content 行 **Only me**；评论关闭、复用控件未渲染（目标 False 已满足） |
| branded-content + friends | `--branded-content --privacy friends` | `0` | `https://www.tiktok.com/@lukechen95/video/7704956629594279182` | 帖子页 **Friends only** + **Paid partnership**；Content 行 **Friends** |
| 自定义封面 | `--thumbnail videos/demo.png --privacy only-me` | `0` | `https://www.tiktok.com/@lukechen95/video/7704957967111638286` | `Edit cover` → `Upload cover` → 预览 → Save 全链路通过；帖子页 **Private**；截图 `.local/tiktok19/custom-cover-post.png` |
| 定时发布 | `--schedule 2026-11-06 22:00 --privacy followers` | `0` | Scheduled 行：`TB19 scheduled followers 2200` | Content/Scheduled 列表显示 **10:00 PM (GMT+8) Shanghai**、**Followers**；未等待到点发布。only-me 下 Schedule 被 TikTok 禁用（已补明确报错） |
| 图文多图 | `upload-note --images videos/demo.png videos/demo1.png videos/demo2.png --title "TB19 note multi v2" --note "TB19 note body" --tags tbtest,note --privacy only-me` | `0` | `https://www.tiktok.com/@lukechen95/video/7704966090018786574` | Content 行 **Only me** + `TB19 note body #tbtest #note`；帖子页 Description/tags 正确；Title 已填写但 Web 帖子页不展示；3 张图，第 1 张为封面；截图 `.local/tiktok19/note-multi-post.png` |
| 图片帖设置项（私有账号旧结果） | `upload-note ... --no-comments --aigc --your-brand` | `1` | — | 当时未找到正确的 Show more；已在公开账号复验并修复，见上一行 |
| 图片帖选项展开修复 | `--privacy public --no-comments --aigc --your-brand` | `0` | 同上 `7704976028485176590` | 图片页没有 `advanced_settings_container`，全局 **Show more** 才展开评论/AIGC/品牌；修复后逐项回读并发布成功 |

## 结论

- **已验证**：本地登录/check、私有账号 `only-me`/`followers`/`friends`、公开账号无新参数发布、`--privacy public`（Everyone）与 `followers` 严格失败、`--no-comments`、`--disable-reuse`（账号不渲染时按目标 False 满足）、`--aigc`（帖子显示 AI 标签）、`--your-brand`（Promotional content）、`--branded-content` + friends（Paid partnership）、自定义封面、定时创建与时间/隐私回读、图文 3 图/Description/tags/首图封面、**公开账号图片帖选项**（评论/AIGC/品牌）。
- **条件未满足/未等待**：定时帖到点发布未等待（且切换公开账号后旧 Followers 定时帖从 Scheduled 列表消失）；图文 Title 不在 Web 帖子页展示（已填写，未做编辑页复核）。
- **公开账号首项文案**：Content 行显示 **Everyone**，与公开账号预期一致。
- **发现并修复**：Content `read_result` 原取第一条，定时帖排在最前导致图文帖误取定时帖 ID；已改为按标题/正文/标签匹配，并在真实 Content 页验证图文 `7704966090018786574`、视频 `7704956309300382989` 均正确。

## 真实环境发现并修复

1. `LOCAL_CHROME_PATH` 为空时 `executable_path=""` 导致浏览器启动失败 → 空值改用 Patchright 自带 Chromium。
2. `--lang` 被拆成两个 tokens，Patchright 报 “Arguments can not specify page to be opened” → 改为 `--lang=en-US` 单参数。
3. 登录后入口等待 5s 与客户端渲染竞态 → MLX 15s / 本地 20s。
4. 首次上传出现 `Turn on automatic content checks?` 弹窗与 react-joyride 引导遮罩拦截点击 → `dismiss_blocking_overlays`（Cancel / 点击遮罩）+ 编辑器点击重试。
5. 有头浏览器使用系统中文，英文入口选择器失效 → 本地 context `locale=en-US`；入口优先 `data-e2e="select_video_button"`。
6. 图片页 Title 输入框在选图后才出现 → `ensure_mode` 改用 `input[type=file][accept*="image"]` 作为入口信号。
7. 隐私下拉当前是 `div[role="option"]`，不是 `li[role="option"]` → 改为按 role 匹配。
8. 隐私选项渲染在 portal 里，不在 `video_visibility_container` 内部 → 增加 `fallback_scope`（在 `locator_base`/页面根上找 `[role="option"]`）。
9. Content 列表不再使用 `data-tt="components_PostTable_Container"` → `read_result` 改为等待/读取 `a[href*="/video/"]` 并提取 `/video/<id>`。
10. macOS 上 `Control+A` 不能全选 caption（残留旧文案）→ 使用 Playwright `ControlOrMeta+A`。
11. 评论复选框的原生 input 被 SVG 覆盖，且 `Checkbox__root--disabled-false` 被误判为 disabled → 点击可见 label + 精确 disabled class 判断。
12. AIGC/品牌开关藏在折叠的 `advanced_settings_container` 里；首个候选是隐藏 input → 先展开高级设置，开关优先 `.Switch__content`。
13. 品牌复选框的 label 没有可访问名，文本在 label 外层兄弟节点 → 用 XPath 从文本 span 反查同级 label。
14. Playwright 应用 storage_state 时偶发导航竞态 → 本地 context 创建重试 3 次。
15. `change_language` / 上传页 `goto` 等 `load` 会超时 → 改 `domcontentloaded`，语言切换 best-effort。
16. 定时首次点击 `Schedule` 会弹 `Allow` 权限；日期/时间控件是 `Select date` / `Select time` combobox + `DatePicker__day` / `role=option`，已重写 `apply_schedule` 并回读日期/时间。
17. 私有账号 `only-me` 下 TikTok 禁用 Schedule → 明确报错退出 `1`，不再 30s 轮询。
18. 定时帖没有即时发布链接 → `read_result` 对定时帖返回 `None`，以 Scheduled 列表为验收依据。
19. 图片页 Title/Description 在选图后才渲染，入口用 image file input；Title/Description 重试放宽到 20s。
20. 图片页 Post 按钮没有 `data-e2e` → 用 `button:has-text("Post")` 候选；图片入口等待改为 attached。
21. 图片页没有 `advanced_settings_container`，评论/AIGC/品牌在全局 **Show more** 之后才可见；已加全局 Show more 兜底。公开账号 `--privacy public --no-comments --aigc --your-brand` 图片帖发布成功，帖子页显示 Promotional content + AI 标签。
22. 公开账号的发布点击会出现 `Post now` 确认弹窗；已有兜底在真实发布中触发并成功。
23. 切换到公开账号后，之前创建的 Followers 定时帖不再出现在 Scheduled 列表（账号类型变更可能导致取消）；定时创建/时间/隐私已在切换前核对，到点发布仍未等待。
