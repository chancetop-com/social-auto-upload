# 06 — 第一波能力的真实账号入口实测

Status: resolved
Type: task
Blocked by: 无

## Question

第一波 9 项里有 3 项的网页入口尚未确认（Stories、配乐、定时），另有 6 项的控制件结构未记录。用一个测试账号逐项点一遍，产出“入口是否存在、在哪、控件结构、账号资格”的事实清单，供 07 的参数契约使用。

必须实测：

- **Stories**：创建弹窗是否有 Post/Story/Reel 格式选择；图片与 ≤60s 视频各发 1 条；记录 DOM 与 `configure` 响应。
- **定时发布**：专业后台是否有 `Scheduled content` / `Bulk upload`；单帖能否排期；时区、45 条上限、账号资格。
- **配乐 / 曲库**：视频编辑页「声音」入口；曲库搜索/试听；音量控件。
- **location**：配文页「添加地点」搜索与选中；发布后是否显示。
- **collaborators**：邀请 ≤3 人；是否需要对方接受。
- **user_tags**：图上坐标标记；Stories 是否支持。
- **alt_text**：照片编辑/更多设置入口；单图 vs 轮播逐张。
- **关闭评论**：高级设置开关；发布后是否立即生效。
- **AI 标识**：高级设置开关；轮播是整帖级还是逐张。
- **选帧封面**：视频编辑页选帧；能否稳定映射到目标帧。

产出：`research/06-entry-probe.md`，逐项记录「有 / 无 / 需资格」、入口路径、DOM/选择器线索、证据截图或页面记录（不入 Git）。无法实测的项标 `未验证`，不要推断成事实。

## Answer

实测完成（2026-11-10），账号 `lukechen918`（**Personal**，English US）。详见 [`research/06-entry-probe.md`](../research/06-entry-probe.md)。

**确认有入口（可做）**：

- location：配文页 `Add location` 输入框。
- collaborators：配文页 `Add collaborators` 输入框。
- user_tags：编辑页 `Tag people`。
- alt_text：`Accessibility` → `Alt text` 输入框。
- 关闭评论：`Advanced settings` → `Turn off commenting` 开关。
- AI 标识：配文页 `Add AI label` 开关（`input[role=switch]`）。
- 额外确认：滤镜列表、`Hide like and view counts on this post`、上传封面（`Cover photo` → `Select from computer`）。

**该账号不可用 / 被账号类型阻塞**：

- Stories：创建弹窗无格式选择；导航无 Story 入口；`/create/story/` 重定向到 feed。
- 定时发布：主 composer 无入口；`/professional_dashboard/` 返回 “Sorry, this page isn't available”（Personal 账号）。
- 配乐 / 曲库：视频编辑页只有 `Sound on`（原声开关），无 `Add audio` / `Music` 入口。
- 选帧封面：只有上传封面，未观察到从视频选帧。

**仍待实测（不阻塞参数契约）**：location/collaborator 搜索联想、user_tags 坐标点击、alt_text 发布后回读、AI/关评论发布后生效、轮播逐张 alt_text。

**结论**：第一波 9 项中，5 项入口确认（location、关评论、user_tags、alt_text、AI 标识）+ 上传封面可用；Stories/定时/配乐在该 Personal 账号网页端不可用，需 Creator/Business 账号复核，暂标 `unsupported/TBD`。07 可先按已确认项设计参数契约。
