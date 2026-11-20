# AI 标识、地点与标签：七平台支持调查

- 调查日期：2026-11-20
- 范围：当前 `sau` 支持的 7 个发布平台（小红书、Rednote、TikTok、YouTube、Facebook、Facebook Page、Instagram）
- 口径：先看**桌面网页发布流程**（本仓库用 Playwright 驱动浏览器），再看现有代码是否已接入。移动端独有能力单独标注。
- 证据等级：`[code]` = 仓库源码/测试；`[official]` = 平台官方帮助中心/博客；`[shipped-js]` = 平台线上发布页 bundle（无公开帮助文档时的第一方证据）；`[secondary]` = 非官方资料，仅作线索；`[needs-live]` = 必须登录真实账号实测才能定。

## 0. 结论摘要

| 平台 | AI 标识 | 地点 | 标签 | 现有接入情况 |
|---|---|---|---|---|
| 小红书 | ✅ 原生：内容类型声明 →「笔记含AI合成内容」 | ✅ 原生：「添加地点」；代码有休眠实现 | ✅ 原生：话题（≤10） | AI/标签已接入；地点未暴露 CLI |
| Rednote | ✅ 原生：同小红书 | ✅ 原生：同小红书；代码有休眠实现 | ✅ 原生：话题（≤10） | AI/标签已接入；地点未暴露 CLI |
| TikTok | ✅ 原生：`AI-generated content` 开关 | ✅ 原生：`Add location`（Web 支持；37 国 + 18 岁门控；每帖 1 个） | ✅ 原生：hashtag（≤50） | AI/标签已接入；地点未接入 |
| YouTube | ✅ 原生：Attributes → `AI use` | ✅ 原生：`Recording date and location` → `Video location` | ✅ 原生：关键词 Tags（非 hashtag） | 仅标签已接入 |
| Facebook（个人主页） | ✅ 原生：发帖器 `AI label` → `Add AI Label` | ✅ 原生：`Check in` | ✅ 原生：正文 hashtag | 仅标签已接入 |
| Facebook Page（Business Suite） | ⚠️ Business Suite 无入口；发布后 Graph API 可改 | ✅ 原生：Post details → location | ✅ 原生：正文 hashtag | 仅标签已接入 |
| Instagram | ✅ 原生：`Add AI label` | ✅ 原生：`Add location` | ✅ 原生：配文 hashtag | 三项均已接入 |

**一句话结论**

1. **标签是唯一 7/7 全覆盖的字段**，但实际是三种不同东西：YouTube 的 SEO 关键词、TikTok/IG/Facebook 的正文 hashtag、小红书/Rednote 的话题实体。
2. **AI 标识在 6 个平台有已确认的网页入口**（TikTok、YouTube、Facebook、Instagram 有官方文档；小红书、Rednote 由线上 bundle + 本仓库真机干跑/验收确认），Facebook Page 的 Business Suite 没有发帖前入口（只能发布后走 Graph API v27 的 `is_ai_generated`）；当前只接了 4 个（TikTok、Instagram、小红书、Rednote）。小红书/Rednote 的 AI 是「内容类型」单选，不能与虚构/营销/来源声明叠加；这与 IG/TikTok 的独立布尔开关语义不同。
3. **地点原生 7/7 可用**，当前只有 Instagram 真正接入。TikTok 的 Web 地点有 37 国 + 18 岁门控且每帖只能 1 个；小红书/Rednote 已有可运行的 `set_location()`，只是发布链里被注释掉且没有 CLI 参数；这是成本最低的补齐点。
4. **不能用一个同名布尔值抽象全部平台**：YouTube 的 location 是「拍摄地点」，Facebook 是「签到地点」，小红书是「笔记 POI」，TikTok 若可用也是 POI；YouTube 的 AI 是 Yes/No 调查，小红书是单选内容类型，其余是开关。

## 1. 逐平台现状

### 1.1 小红书（`sau xiaohongshu`）

- **AI 标识**：`--content-type ai`，对应下拉项「笔记含AI合成内容」`[code]`（`uploader/xiaohongshu_uploader/main.py:84-96`）。官方没有公开帮助页，但线上发布页 bundle 含同一组声明项 `[shipped-js]`。它和 `fiction` / `marketing` / `self-shot` / `repost` 是**同一个单选下拉**的互斥选项，不是独立开关。设置失败只记 warning 并继续发布，不是硬闸 `[code]`（`main.py:2327-2356`）。
- **地点**：发布页顶部有「添加地点」下拉；`set_location()` 已实现「输入 → 等联想 → 精确匹配候选」的完整流程 `[code]`（`main.py:1754-1820`），但发布链中调用被注释掉（`main.py:2780`），且 CLI 没有 `--location`。线上 bundle 显示 Web 端只支持 1 个 POI，多 POI 编辑会提示前往 App `[shipped-js]`。当前 `--shoot-location` **不是**地点标签，它只用于「内容来源声明 → 自主拍摄」弹窗里的拍摄地点 `[code]`（`sau_commands/xiaohongshu.py:86-94`）。
- **标签**：`--tags` 创建真正的话题实体，最多 10 个，超过截断并 warning；插入失败降级为纯文本，不阻断发布 `[code]`（`main.py:299`、`1904-2140`）。

### 1.2 Rednote（`sau rednote`）

- 与小红书是两套独立实现，但当前结构、声明、地点、话题逻辑基本同构。
- **AI 标识**：`--content-type ai`，同样映射「笔记含AI合成内容」`[code]`（`uploader/rednote_uploader/main.py:91-103`）。
- **地点**：`set_location()` 存在（`main.py:1683`），发布链中同样被注释（`main.py:2811`），CLI 未暴露。
- **标签**：话题实体，最多 10 个 `[code]`（`main.py:280`、`1849-2105`）。

### 1.3 TikTok（`sau tiktok`）

- **AI 标识**：`--aigc` / `--no-aigc`，位于 `Show more` 的 `AI-generated content`；首次开启可能弹 `Turn on` 确认框 `[code]`（`uploader/tk_uploader/main_chrome.py:1395-1550`；`sau_commands/tiktok.py:95-112`）。官方说明：桌面端 `Click Upload → See more → Turn on AI-generated content`，发布后不可再改 `[official]`（<https://www.tiktok.com/tns-inapp/pages/ai-generated-content>）。
- **地点**：TikTok Creator Academy 明确支持 **TikTok Studio Web 版**，发布前可选一个推荐地点或搜索地点；条件是**国家/地区白名单（37 个，含美/英/加/澳/日/巴西/德/法等）+ 年满 18 岁 + 每帖仅 1 个地点** `[official]`（<https://www.tiktok.com/creator-academy/article/tiktok-location-feature>）。移动端同样有 `Add a location` `[official]`（<https://support.tiktok.com/en/using-tiktok/creating-videos/making-a-post>）。现有代码完全没有 location 路径；需要按账号所在国家/年龄做前置判断，否则应明确 `unsupported`。
- **标签**：`--tags` 在标题/描述里插入真实 hashtag 实体，最多 50 个；图片帖会先做 90/4000 字符与 50 hashtag 的静态校验 `[code]`（`main_chrome.py:2402-2550`；`sau_commands/tiktok.py:358-393`）。
- **不要混淆**：`--your-brand` / `--branded-content` 是商业推广声明，不是 AI 标识。

### 1.4 YouTube（`sau youtube`）

- **AI 标识**：官方在 `Attributes` → `AI use` 提供 Yes/No 调查，适用于真实感 AI 生成/实质性修改内容；发布后多数情况仍可修改 `[official]`（<https://support.google.com/youtube/answer/14328491>）。当前代码没有接入 `[code]`。
- **地点**：官方在 `Show more` → `Recording date and location` → `Video location` 提供地点搜索与选择，属于「拍摄地点」元数据，观众可点击搜索同地点视频 `[official]`（<https://support.google.com/youtube/answer/7638112>、<https://support.google.com/youtube/answer/57407>）。当前代码没有接入。
- **标签**：`--tags` 填入 Studio 的 Tags 关键词框，逗号连接并截到 500 字符 `[code]`（`uploader/youtube_uploader/main.py:517-530`）。注意它**不是** hashtag，观众不可见。
- 与 AI 相邻但不同的字段：`Altered content` 与 `AI use` 是同一披露体系的不同代际文案；不要同时实现两个 UI 入口。

### 1.5 Facebook 个人主页（`sau facebook`）

- **AI 标识**：官方步骤为「Create a post → 点 `AI label off` → 打开 `Add AI Label`」`[official]`（<https://www.facebook.com/help/7434563519957988>）。属于逐帖开关；图片不强制，真实感视频/音频才强制。当前代码没有接入 `[code]`。
- **地点**：官方发布器有 `Check in`；在首页 composer 点 `Check in` 后可搜索或从列表选择地点 `[official]`（<https://www.facebook.com/help/174846215904356>）。Business Suite 帮助也列出「add hashtags, a location, a feeling/activity」`[official]`（<https://www.facebook.com/business/help/942827662903020>）。当前代码没有接入。
- **标签**：`--tags` 以 `#tag` 形式拼进正文 `[code]`（`uploader/meta_uploader/facebook_uploader/main.py:266-267`）。

### 1.6 Facebook Page（`sau facebook-page`）

- **AI 标识**：官方 Business Suite 创建帖子文档只列 media、text、hashtags、location、feeling/activity、audience、scheduling，**没有发帖前 AI 披露控件** `[official]`（<https://www.facebook.com/business/help/942827662903020>）。Graph API v27.0（2026-11-04）新增 Page Post 的 `is_ai_generated`，但用于**编辑已存在的 Page 帖子**，不是创建时设置 `[official]`（<https://developers.facebook.com/documentation/development/graph-api/changelog/version27.0>）。当前代码没有接入。
- **地点**：Business Suite 创建帖子的 `Post details` 下方有 location 图标，可搜索地点 `[official]`（<https://www.facebook.com/business/help/942827662903020>）。注意代码里的 `_select_publish_location()` **不是地点标签**，它是选择「发布主体 Page」的下拉 `[code]`（`uploader/meta_uploader/facebook_page_uploader/main.py:341-378`）。
- **标签**：`--tags` 拼进正文；Reel 有独立标题时拼到正文，不与标题混 `[code]`（`main.py:317-318`、`413-414`）。

### 1.7 Instagram（`sau instagram`）

- **AI 标识**：`--ai-generated` / `--no-ai-generated`，对应配文页 `Add AI label` 开关；入口缺失且请求开启时退出 1，请求关闭时视为 `default_off` `[code]`（`sau_commands/instagram.py:147-160`；`uploader/meta_uploader/insgraph_uploader/controls/ai_label.py`）。**注意官方帮助目前称该功能「不在电脑端提供」，与本仓库 2026-11-10 的真实账号网页发布验收（发布后出现 `AI content` 标签）冲突**；应以实测为准，并预期存在账号灰度/地区差异 `[needs-live]`。
- **地点**：`--location TEXT`，在联想列表中按「忽略大小写与多余空白」精确匹配；无匹配退出 1、不发布 `[code]`（`controls/location.py`；`docs/CLI.md:640`）。
- **标签**：`--tags` 与标题、正文合并为配文，总长 ≤2200 `[code]`（`options.py:214-225`）。
- 唯一有结构化逐项结果契约的平台：`options.{location,alt_text,comments,ai_generated}` → `{requested,applied,status,reason?}`，状态为 `not_requested|set|default_off|unsupported|mismatch` `[code]`（`docs/CLI.md:658-660`）。
- 官方网页流程确认：照片发布页可 `Write a caption`、`Add your location`、`Accessibility`（替代文字）、`Advanced Settings`（关闭评论）`[official]`（<https://help.instagram.com/442418472487929>、<https://help.instagram.com/408972995943225>）。AI 标签的官方帮助以移动端 `Add AI label` 描述，网页端由本仓库代码与真实账号验收确认 `[code]`（<https://help.instagram.com/761121959519495>）。

## 2. 当前 CLI 覆盖矩阵

| 能力 | 小红书 | Rednote | TikTok | YouTube | Facebook | FB Page | Instagram |
|---|---|---|---|---|---|---|---|
| AI 标识 | `--content-type ai` | `--content-type ai` | `--aigc/--no-aigc` | 无 | 无 | 无 | `--ai-generated/--no-ai-generated` |
| 地点 | 无 CLI（代码休眠） | 无 CLI（代码休眠） | 无 | 无 | 无 | 无 | `--location` |
| 标签 | `--tags`（话题） | `--tags`（话题） | `--tags`（hashtag） | `--tags`（关键词） | `--tags`（hashtag） | `--tags`（hashtag） | `--tags`（hashtag） |

三态约定不一致：

- Instagram、TikTok 的 AI/评论开关是**三态**：不传 = 不动页面默认；显式 true/false 才操作。
- 小红书/Rednote 的 AI 是**内容类型枚举**：不传 = 不动；传 `ai` = 选中该项；没有单独的「关闭 AI」语义，因为下拉本身就是单选。
- YouTube 的 AI 是**Yes/No 调查**；不传时是否要主动选 No，需要产品决策（不选可能触发平台自动检测/自动打标）。

## 3. 差距与实现成本

### 3.1 低成本、代码已有或控件简单

| 项 | 平台 | 说明 |
|---|---|---|
| 地点 | 小红书、Rednote | `set_location()` 已存在，只差 CLI 参数、参数校验、接线、结果记录与真实账号验收。候选匹配是精确文本，失败应明确报候选。 |
| AI | YouTube | `Attributes → AI use` 的 Yes/No；需要处理「不传 = 不动」与「显式 No」的区别。 |
| 地点 | YouTube | `Show more → Recording date and location → Video location`；需要搜索 + 选择候选，候选归一化规则与 IG 类似。 |
| AI | Facebook 个人主页 | 发帖器 `AI label` 按钮 + `Add AI Label` 开关；控件简单。 |
| 地点 | Facebook 个人主页 / Page | `Check in` / Post details location；需要搜索 + 选择地点候选。 |
| 标签 | 全部 | 已覆盖，不建议重做；只需在文档中把三种语义说清。 |

### 3.2 需要真实账号实测才能定

| 项 | 平台 | 风险 |
|---|---|---|
| 地点 | TikTok Web | 官方确认 Web 支持，但仅 37 国、18+、每帖 1 个地点；需要在代码里做账号国家/年龄前置判断，选择器仍需实测。 |
| AI | Facebook Page | Business Suite 没有发帖前入口；Graph API v27 的 `is_ai_generated` 只能编辑已有帖子，不能作为创建时方案。若产品要求创建时披露，只能记录 `unsupported`。 |
| AI | Instagram | 已有真实账号验收（English UI / Personal），但官方帮助称网页端不提供、本仓库实测可用，二者冲突；中文界面、专业账号、托管模式仍未验收。 |
| 地点 | 小红书/Rednote | 休眠代码的 DOM 可能已过时；需要重新确认真实页面与候选精确匹配行为。 |
| AI | 小红书/Rednote | 「内容类型声明」失败只 warning，若要求合规硬闸，需要改成可配置的硬失败。 |

### 3.3 语义冲突（设计时最重要）

1. **AI + 其他声明**：小红书/Rednote 的 AI、虚构、营销、自主拍摄、来源转载是同一个单选下拉。若统一 API 允许 `--ai-generated` 与 `--content-type marketing` 同时传，平台无法表达；必须在静态校验阶段拒绝。
2. **地点不是一种东西**：YouTube 是拍摄地点元数据，Facebook 是签到 POI，小红书是笔记 POI，Instagram 是 POI。统一 `--location` 可以，但帮助文本和结果语义要分平台说明；不要承诺「同一地点名在所有平台都能命中」。
3. **标签不是一种东西**：YouTube 关键词 ≠ hashtag ≠ 话题。统一 `--tags` 可以保留，但文档必须写清「YouTube 不生成 #，小红书生成话题实体，TikTok/IG/FB 生成正文 hashtag」。
4. **AI 标签不可撤销性**：TikTok 发布后不能改 AI 标签 `[official]`；YouTube 多数可改；IG 可在发布前设置。自动化应在发布前一次性完成，不能依赖事后补救。

## 4. 建议的统一契约（供后续实现参考）

- **标签**：保持现状 `--tags`，不新增别名；在 `docs/CLI.md` 增加「平台语义」小节。
- **AI 标识**：统一 `--ai-generated` / `--no-ai-generated`（三态），各平台映射：
  - TikTok → `aigc`；
  - Instagram → `ai_generated`；
  - YouTube → `AI use` Yes/No；
  - Facebook → `Add AI Label`；
  - FB Page → 先实测 Business Suite 是否有 `Add AI Label`；没有则记录 `unsupported`，不要假装支持；
  - 小红书/Rednote → 映射到 `--content-type ai`，并在同时传其他 `--content-type` 时退出 2。
- **地点**：统一 `--location TEXT`，三态（不传 = 不动）。各平台映射：
  - Instagram / 小红书 / Rednote：联想列表精确匹配，无匹配退出 1；
  - YouTube：`Video location` 搜索并选择；
  - Facebook / FB Page：`Check in` / location 搜索并选择；
  - TikTok：Web 官方支持，但需先判断账号国家（37 国白名单）与 18+；不满足则 `unsupported`。
- **结果**：建议把 Instagram 的 `options` 结构推广到其余平台，至少记录 `{requested, applied, status, reason?}`；否则跨平台调度层无法区分「没请求」「设置了」「平台不支持」「设置失败」。
- **失败策略**：AI 标识若平台要求强制披露，建议提供硬失败模式；地点和标签保持现有的「精确匹配失败即停止」与「标签降级」策略，不要静默猜测。

## 5. 待实测清单

| # | 平台 | 要确认的事 |
|---|---|---|
| 1 | TikTok Web | `Add location` 的实际位置与候选结构；账号国家/年龄判断；图文帖是否同样有地点入口 |
| 2 | Facebook Page | 确认 Business Suite 确实没有发帖前 AI 标签；若要用 Graph API，评估发布后编辑的合规时序 |
| 3 | YouTube | `AI use` 的 DOM 结构（radio/下拉）、`Video location` 候选结构、`No` 是否可显式设置 |
| 4 | Facebook 个人主页 | `AI label off` 按钮的展开态、`Add AI Label` 开关状态读取 |
| 5 | 小红书 / Rednote | 休眠 `set_location()` 对当前真实页面的有效性、候选匹配、失败文案 |
| 6 | Instagram | 中文界面、专业账号、MLX/AdsPower 下 AI 标签与地点入口 |

## 6. 主要证据

- 本仓库：
  - `uploader/xiaohongshu_uploader/main.py:84-96, 1754-1820, 2199-2360, 2780`
  - `uploader/rednote_uploader/main.py:91-103, 1683, 2811`
  - `uploader/tk_uploader/main_chrome.py:1395-1550, 2402-2550`
  - `uploader/youtube_uploader/main.py:517-530`
  - `uploader/meta_uploader/facebook_uploader/main.py:266-267`
  - `uploader/meta_uploader/facebook_page_uploader/main.py:317-318, 341-378, 413-414`
  - `uploader/meta_uploader/insgraph_uploader/options.py:34-58, 214-225`
  - `sau_commands/instagram.py:147-160`
  - `docs/CLI.md:630-666`
- 平台官方：
  - YouTube AI：<https://support.google.com/youtube/answer/14328491>
  - YouTube 地点：<https://support.google.com/youtube/answer/7638112>
  - YouTube 上传字段：<https://support.google.com/youtube/answer/57407>
  - TikTok AI：<https://www.tiktok.com/tns-inapp/pages/ai-generated-content>
  - TikTok 地点（Web 支持 + 37 国/18+ 门控）：<https://www.tiktok.com/creator-academy/article/tiktok-location-feature>
  - TikTok 发帖（含移动端地点）：<https://support.tiktok.com/en/using-tiktok/creating-videos/making-a-post>
  - YouTube 标签：<https://support.google.com/youtube/answer/146402>
  - Facebook AI 标签：<https://www.facebook.com/help/7434563519957988>
  - Facebook 签到/地点：<https://www.facebook.com/help/174846215904356>
  - Facebook hashtag：<https://www.facebook.com/help/587836257914341>
  - Meta AI 标识说明：<https://www.meta.com/help/artificial-intelligence/1783222608822690/>
  - Business Suite 发帖（地点）：<https://www.facebook.com/business/help/942827662903020>
  - Graph API v27.0（Page Post `is_ai_generated`）：<https://developers.facebook.com/documentation/development/graph-api/changelog/version27.0>
  - Instagram AI 标签：<https://help.instagram.com/761121959519495>
  - Instagram 发布页地点：<https://help.instagram.com/408972995943225>
  - Instagram 电脑发帖（配文/地点/替代文字/关评论）：<https://help.instagram.com/442418472487929>
  - Instagram hashtag：<https://help.instagram.com/351460621611097>
- 平台线上发布页（无公开帮助文档时的第一方证据）：
  - 小红书：<https://creator.xiaohongshu.com>（发布页 bundle 含「笔记含AI合成内容」「添加地点」「添加话题」；Web 单 POI）
  - Rednote：<https://creator.rednote.com>（发布页 bundle 含同名声明、地点与话题控件）
