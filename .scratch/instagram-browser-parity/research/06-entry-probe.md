# 06 — 第一波能力入口实测记录

- 日期：2026-11-10
- 账号：`lukechen918`
- 账号类型：**Personal**（设置页显示 “Switch to professional account”；`/professional_dashboard/` 返回 “Sorry, this page isn't available”）
- 界面语言：**English (US)**（已从中文切换）
- 方法：应用内浏览器，真实登录；先只打开界面看入口，不发布。
- 状态：**部分完成**；定时发布被账号类型阻塞，配乐/选帧需要视频。

## 0. 会话确认

| 项 | 结果 |
|---|---|
| 已登录标记 `a[href^="/direct/inbox/"]` | ✅ |
| 账号类型 | Personal |
| 是否链接 Facebook Page | 未验证（Personal 账号无 Page 绑定概念） |
| 界面语言 | English (US) |
| 专业后台 `/professional_dashboard/` | ❌ “Sorry, this page isn't available” |

## 1. 创建入口与非发布检查（English UI）

| 检查项 | 结果 | 证据/选择器 |
|---|---|---|
| 创建入口 | 左侧导航 “New post”（SVG aria-label） | `a._a6hd[href="#"]` 第 2 个 |
| 创建弹窗标题 | **Create new post** | `[role=dialog]` heading |
| 是否有格式选择（Post/Story/Reel） | ❌ 没有 | 空 composer 只有 “Drag photos and videos here” / “Select from computer” |
| 选素材 input 的 accept | `image/avif,image/jpeg,image/png,image/heic,image/heif,video/mp4,video/quicktime` | 单个 `input[type=file][multiple]` |
| 裁剪页标题/动作 | **Crop** / **Next** | 无格式选择；只有 Back、Crop、Zoom、Media library |
| 编辑页 | **Edit** / **Next**；滤镜列表（Aden…Original…Slumber）；**Tag people** | 滤镜 API 不支持；Tag people = user_tags |
| 配文页 | **Create new post** / **Share** | 见下 |

## 2. 逐项能力（English UI）

### 2.1 Stories（图/视频）

| 问题 | 结果 |
|---|---|
| 创建弹窗是否有 Story 格式选择 | ❌ 没有 |
| 左侧导航是否有 Story 入口 | ❌ 没有（只有 “New post”） |
| `/create/story/` 直达 | ❌ 重定向到首页 feed |
| 首页是否有 “Your story” 入口 | ❌ 未观察到 |
| 结论 | **该 Personal 账号的网页端没有 Story 发布入口**；可能是账号类型/灰度限制，需专业账号复核 |

### 2.2 定时发布

| 问题 | 结果 |
|---|---|
| 主 composer / 高级设置是否有定时入口 | ❌ 没有 |
| 专业后台是否有 Scheduled content | ❌ `/professional_dashboard/` 不可用（Personal） |
| 结论 | **被账号类型阻塞**；需 Creator/Business 账号才能验证 |

### 2.3 配乐 / 曲库

| 问题 | 结果 |
|---|---|
| 图片编辑页是否有声音入口 | ❌ 没有（图片不支持） |
| 视频编辑页是否有声音入口 | 未验证（需要视频） |
| 结论 | 待视频实测 |

### 2.4 location

| 问题 | 结果 |
|---|---|
| 配文页是否有 “Add location” | ✅ 有，`input[placeholder="Add location"]` |
| 搜索联想是否可用 | 未验证 |
| 选中后发布是否显示地点 | 未验证（不发布） |
| 结论 | **入口确认**；联想/回读待实测 |

### 2.5 collaborators

| 问题 | 结果 |
|---|---|
| 配文页是否有 “Add collaborators” | ✅ 有，`input[placeholder="Add collaborators"]` |
| 能否搜索账号 | 未验证 |
| 是否需要对方接受 | 未验证 |
| 最多几人 | 未验证（API 上限 3） |
| 结论 | **入口确认**；交互待实测 |

### 2.6 user_tags

| 问题 | 结果 |
|---|---|
| 编辑页是否有 “Tag people” | ✅ 有，`button[aria-label="Tag people"]` |
| 是否可在图上点坐标 | 未验证 |
| Stories 是否支持 | 未验证 |
| 结论 | **入口确认**；坐标点击待实测；**用户决定第一波不做** |

### 2.7 alt_text

| 问题 | 结果 |
|---|---|
| 入口 | **Accessibility** → `input[placeholder="Alt text"]` |
| 单图是否可填写 | ✅ 输入框存在 |
| 轮播是否逐张 | ✅ 已确认：2 图轮播 → 2 个 `Alt text` 输入框 |
| 发布后能否读回 | 未验证 |
| 结论 | **入口确认**；输入与回读待实测 |

### 2.8 关闭评论

| 问题 | 结果 |
|---|---|
| 入口 | **Advanced settings** → **Turn off commenting** 开关 |
| 发布前设置是否生效 | 未验证（不发布） |
| 结论 | **入口确认**；开关可切换，发布后回读待实测 |

### 2.9 AI 生成标识

| 问题 | 结果 |
|---|---|
| 入口 | 配文页 **Add AI label** 开关（`input[role=switch]`，`aria-checked=false`） |
| 轮播是整帖级还是逐张 | 未验证 |
| 发布后是否显示 | 未验证 |
| 结论 | **入口确认**；开关可切换 |

### 2.10 选帧封面

| 问题 | 结果 |
|---|---|
| 视频编辑页是否可选帧 | 未验证（需要视频） |
| 能否稳定映射到目标帧 | 未验证 |
| 与上传封面的优先级 | 未验证 |
| 结论 | 待视频实测 |

## 3. 额外确认（API 没有的网页能力）

| 能力 | 结果 |
|---|---|
| 滤镜 | ✅ 编辑页有完整滤镜列表（API 不支持） |
| 隐藏点赞/浏览量 | ✅ Advanced settings → **Hide like and view counts on this post** |
| 发布前关评论 | ✅ Advanced settings → **Turn off commenting**（API 只能发布后改） |
| 本地文件直传 | ✅ 浏览器直接选本地文件（API 需公网 URL） |

## 4. 结论与阻塞

| 能力 | 入口 | 结论 |
|---|---|---|
| Stories | 无 | 该 Personal 账号网页端无入口；需专业账号复核 |
| 定时发布 | 无 | 被 Personal 账号阻塞；需专业后台 |
| location | 有 | 可做；联想/回读待实测 |
| 关闭评论 | 有 | 可做；发布后回读待实测 |
| 配乐 | 图片无 | 需视频实测 |
| 选帧封面 | 未验证 | 需视频实测 |
| user_tags | 有 | 入口确认；用户决定第一波不做 |
| alt_text | 有 | 可做；输入/回读待实测 |
| AI 标识 | 有 | 可做；开关可切换 |

**下一步需要**：一个 Creator/Business 测试账号（验证 Stories、定时、专业后台），以及一个短视频（验证配乐/选帧）。

## 5. 视频流程补充（videos/demo.mp4，English UI）

| 阶段 | 观察 |
|---|---|
| 创建 | 仍是 **Create new post**；无格式选择 |
| 裁剪 | **Crop** / **Next**；只有 Back、Select crop、Media library |
| 编辑 | **Edit** / **Next**；**Cover photo** → **Select from computer**；**Trim** 时间轴；**Sound on** 开关 |
| 配文 | 标题变为 **New reel**；**Tag people**、**Add a caption... 0/2,200**、**Add AI label**、**Accessibility**、**Advanced settings** |
| 配乐 / 曲库 | ❌ 未观察到 “Add audio” / “Music” 入口；只有 **Sound on**（原声开关） |
| 选帧封面 | ❌ 未观察到从视频选帧；只有 **Select from computer** 上传封面 |
| Share to feed | ❌ 未观察到开关；页面说明 “Your reel will be shared with your followers in their feeds...” |
| 结论 | 视频固定走 Reels；封面=上传图片；配乐/选帧在该 Personal 账号网页端不可用，需 Creator/Business 复核 |
