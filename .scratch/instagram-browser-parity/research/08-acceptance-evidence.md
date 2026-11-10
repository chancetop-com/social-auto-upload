# 08 — 第一波 4 项真发验收证据

- 日期：2026-11-10（本地时间 16:56 发布、16:57 回读、16:58 删除）
- 账号：Personal（不记录账号名 / Cookie / Profile ID）
- 界面语言：English (US)，本地模式固定 `locale=en-US`
- 代码版本：`feat/instagram-parity`（验收时 HEAD `89e8db5`）
- 环境：macOS，工程 Patchright Chrome，本地 cookie 模式，直连

## 结论

四项全部通过：发布前 `options` 回读 = `set`，发布后帖子确实保留地点、替代文字、关闭评论与 AI 标识。
清理：帖子验证后立即用 `sau instagram delete` 删除，服务端返回 `did_delete=true`。

## 正向用例（一条轮播覆盖四项）

```bash
sau instagram upload-note --account <alias> \
  --images demo1.png demo2.png \
  --title "sau 回归测试 20261110-165627" \
  --note "location + alt text + 关闭评论 + AI 标识" \
  --location "Shanghai" \
  --alt-text "第一张：白底样例" --alt-text "第二张：同款样例" \
  --no-comments --ai-generated \
  --result .local/acceptance/publish.json
```

| 项 | 发布前（结果 JSON） | 发布后（帖子页回读） | 结论 |
|---|---|---|---|
| 退出码 / 状态 | `0`，`published`，`media_count=2` | 帖子存在，`content_id` 与响应一致 | ✅ |
| location | `requested=Shanghai`、`applied=Shanghai`、`status=set` | 帖子头部显示 `Shanghai` | ✅ |
| alt_text | 两条 `requested` 与 `applied` 完全一致，`status=set` | 两张图的 `img[alt]` 分别为 `第一张：白底样例` / `第二张：同款样例`（顺序一致） | ✅ |
| comments | `requested=false`、`applied=false`、`status=set` | 帖子页无任何评论输入框（`textarea`/`contenteditable` 计数 0） | ✅ |
| ai_generated | `requested=true`、`applied=true`、`status=set` | 帖子头部显示 `AI content` | ✅ |

帖子 URL：`https://www.instagram.com/p/Dfjh0AAG4u9/`（已删除，仅作记录）。

## 负向用例

| # | 命令要点 | 退出码 | 结果 |
|---|---|---|---|
| 1 | `--location "no-such-place-xyz-123"` | `1` | `status=not_submitted`，`options.location={requested, applied:null, status:mismatch}`，错误信息列出观察到的候选（本次 30 条，展示前 10 条，均为真实地点联想），主页无新帖 |
| 2 | 2 张图 + 1 条 `--alt-text` | `2` | 输出“替代文字数量不符：1 条，图片 2 张”，无浏览器启动日志，未发布 |

## 证据位置（不进 Git）

- 页面截图与 DOM 快照：`.local/acceptance/`（本地临时目录）
  - 配文页四项终态：`probe-20261110-164408-options.png`
  - 发布后帖子页：`20261110-165714-post.png`、`20261110-165734-post.html`
  - 结果 JSON：`publish.json`、`delete.json`、`negative-location.json`
- 失败现场（历史）：`.local/instagram-errors/`

## 验收中发现并修复的问题

真实账号首次跑验收暴露了 5 个只有在真机上才可见的问题，均已修复（同一分支）：

1. 英文界面未固定：`INSTAGRAM_CONTEXT_KWARGS` 为空且本地 context 未应用 → 本地模式固定 `en-US`。
2. `Add AI label` 开关文案在兄弟列，旧实现只向上找一层 → 按“最近含开关的祖先”匹配。
3. `Accessibility` 是内联折叠区（上下排列的 `input[aria-label="Alt text"]`），不是带 `Done` 的模态框 → 改为折叠区 + 逐张 `fill` + `blur`。
4. `Advanced settings` 行没有 `aria-expanded`，且鼠标点击会被覆盖层拦截 → 键盘 `Enter` 激活 + 以内容出现判定展开。
5. 地点联想是 body 级 portal 的无 role 列表；`el.click()` 不触发选中 → 按几何定位滚动容器内的行，用真实指针点击，并以“被点行脱离 DOM”判定选中；选择后列表消失。
6. 首次真发失败：Instagram 在点击创建后弹出 `Turn on Notifications`，旧实现只保护了点击那一下 → 等待素材入口期间主动关闭已知提示，并在整个上传流程注册 locator handler。
7. 删帖失败：作品菜单项由 8 项增至 9 项 → 不再按数量/下标定位，改为精确匹配 `Delete` 菜单项。

## 未覆盖

- 中文界面：未验收（选择器仅英文实测；本地模式已固定英文，托管模式需 Profile 自行保持英文）。
- 专业 / Business 账号：未验收。
- 托管模式（MLX / AdsPower）：未验收（本次为本地 cookie 模式）。
- 视频 / Reel 上的四项组合：本次用图片轮播覆盖；`upload-video` 的选项代码路径相同，但未单独真发。
- 发布后再次编辑、跨设备生效时间等平台侧细节：未验收。
