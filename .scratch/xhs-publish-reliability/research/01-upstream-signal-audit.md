# 上游发布链路可信信号审计（xpzouying/xiaohongshu-mcp）

- 读取方式：`raw.githubusercontent.com` 按 commit 固定读取，未克隆。
- **xiaohongshu-mcp** `main` @ `3b352aa075d63cd5ebae546c9fe7d7d9b81fa7c9`
- **headless_browser** `main` @ `d28e37c7448672550580fca8ff26404aed09a21f`
- go-rod 相关行为引自 `go-rod/rod` `main`（`input.go`、`page.go`、`element.go`）。
- 标注：**代码明确实现** / **注释声称** / **仅推断**。不含评价与建议。

## 1. 发布按钮

`xiaohongshu/publish.go` `findPublishButton()`(490)、`waitForPublishButtonClickable()`(461)、`clickPublishButton()`(444)、`clickPublishWidget()`(554)。

| 项 | 事实 | 标注 |
|---|---|---|
| 轮询 | 15s 窗口、1000ms 间隔；失败时把最后一次 `disabledReason` 拼进错误 | 代码明确实现 |
| 新版选择器 | `xhs-publish-btn`（自定义元素） | 代码明确实现 |
| 新版跳过 | 元素不可见（`isElementVisible`）→ 跳过；`is-publish` 存在且 `== "false"` → 跳过该 widget | 代码明确实现 |
| 新版禁用 | `submit-disabled == "true"` → 返回该 widget 且 reason 非空（视为不可点，**不再尝试旧版**） | 代码明确实现 |
| 属性缺失 | `is-publish` 或 `submit-disabled` 缺失 → 当作可点击 | 代码明确实现 |
| 旧版选择器 | `.publish-page-publish-btn button.bg-red` | 代码明确实现 |
| 旧版禁用 1 | `disabled` 属性**存在即禁用**（不判值，`disabled="false"` 也算） | 代码明确实现 |
| 旧版禁用 2 | `aria-disabled == "true"` | 代码明确实现 |
| 旧版禁用 3 | `class` 命中单词边界 `disabled`（`hasExactClass` 用 `\b` 正则） | 代码明确实现 |
| 顺序 | 先遍历新版；只有新版无可见元素时才落到旧版 | 代码明确实现 |
| 落点 | `ScrollIntoView` → sleep 200ms → `Shape().Quads[0]` → 取所有顶点的外接矩形 → `x = minX + w*0.65`、`y = minY + h/2` | 代码明确实现 |
| 点击方式 | `humanize.ClickAt`（只做视口检查 + 曲线移动 + 按下/抬起），**不走** `stillOn`/元素命中复核 | 代码明确实现 |
| 65% 的理由 | 源码与注释均未说明 | 仅推断（无法归因） |

## 2. 成功信号

`waitPublishSuccess()`(425)，图片 `submitPublish()`(354) 与视频 `submitPublishVideo()` 均传 `15*time.Second`。

- 谓词：`page.Info().URL` **不含** 子串 `/publish/publish` → 成功（`page.Info()` → `browser.pageInfo`，见 rod `page.go`）。标注 **代码明确实现**。
- 轮询 500ms；超时返回「未跳转离开发布页」。标注 **代码明确实现**。
- 不校验作品 ID、不校验 toast/提示文案、不读发布结果接口。标注 **代码明确实现**（缺失亦可从函数体直接读出）。
- 谓词只排除一个子串，因此跳到登录页/验证页/任意其它 URL 同样满足「成功」。标注 **代码明确实现（谓词直接推论）**。
- 发布页常量 `urlOfPublic = https://creator.xiaohongshu.com/publish/publish?source=official`。标注 **代码明确实现**。

## 3. 话题 / 标签

`inputTags()`(721)、`inputTag()`、`findTopicItem()`(867)、`selectTopicItem()`(831)、`verifyInsertedTopic()`(789)。

| 项 | 事实 | 标注 |
|---|---|---|
| 预置 | 正文输入后先按 `ArrowDown` **20 次**（每次间隔 10ms），再连按两次 `Enter`，sleep 1s | 代码明确实现 |
| 输入 | `humanize.Type("#")` → sleep 200ms → `humanize.Type(tag)` | 代码明确实现 |
| 去前缀 | `strings.TrimLeft(tag, "#")` | 代码明确实现 |
| 联想项 | `#creator-editor-topic-container .item`，取子节点 `.name` 的文本；去前导 `#`、`TrimSpace`、`EqualFold` 匹配；要求 `Visible()` | 代码明确实现 |
| 重试 | 共用 5s deadline（`topicItemTimeout`），轮询 200ms，点击最多 3 次（`topicClickAttempts`），每次点击前重新查找（注释：列表会重绘） | 代码明确实现 |
| 无匹配 | 不中止，打 warn 并补一个空格，保留纯文本 `#tag` | 代码明确实现 |
| 回读 | 点选联想项**前**记录 `a[data-topic]` 数量 `previous`；要求之后数量 **严格等于 previous+1**；取 `nodes[previous]` | 代码明确实现 |
| 回读校验 | `data-topic` 按 JSON 解析取 `name`，与去空格的 tag `EqualFold`；不等即报错中止 | 代码明确实现 |
| 回读窗口 | `editor.Timeout(time.Second)`，50ms 轮询 | 代码明确实现 |
| 语义 | 判据是**编辑器内**话题节点，不是下拉项被点中 → set-then-readback | 代码明确实现 |

## 4. 图文上传完成

`uploadImages()`(249)、`waitForUploadComplete()`(325)、`findImageUploadInput()`(283)。

- 逐张 `SetFiles`，每张后等预览节点数 `>= i+1`，然后 sleep 1s 再传下一张。标注 **代码明确实现**。
- 计数选择器 `.img-preview-area .pr`，`len()` 计数；轮询 500ms；**单张上限 60s**。标注 **代码明确实现**。
- 判据是预览 DOM 数量，不读上传接口响应、不看进度条/错误态。标注 **代码明确实现**（缺失可由函数体直接读出）。
- 首个输入框 `.upload-input`；后续 `input[type="file"]` 中按 `accept` 含 `image/` 或 `.jpg/.jpeg/.png/.webp/.heic` 过滤，否则退回第一个。标注 **代码明确实现**。

## 5. 视频就绪

`publish_video.go` `uploadVideo()`(79)。

- 输入框 `.upload-input`，失败回落 `input[type='file']`；`MustSetFiles`。**代码明确实现**。
- 唯一「处理完成」信号：`waitForPublishButtonClickable(pp, 10*time.Minute)` —— 发布按钮变为可点击。**代码明确实现**。
- 外层 `pp := page.Timeout(5 * time.Minute)`；两处时限同时存在（10 分钟窗口 vs 5 分钟 page deadline），先到者生效。前者 **代码明确实现**；「5 分钟 deadline 先触发」 **仅推断**（取决于 rod 超时传播）。
- 不做单独的转码/上传完成探测。**代码明确实现**。

## 6. 风控页分类

`xiaohongshu/page_check.go` `classifyBlockedPath()`(29)、`classifyBlockedURL()`(43)、`CheckPageBlocked()`(55)。

| 项 | 事实 | 标注 |
|---|---|---|
| 常量 | `captchaPath = /website-login/captcha`、`loginPath = /website-login` | 代码明确实现 |
| 判定 | 路径 == 常量或其 `常量+"/"` 前缀；验证页优先匹配 | 代码明确实现 |
| 未知子路径 | 一律归登录页（注释：给调用方的指引更安全） | 代码明确实现 + **注释声称** |
| 只看路径 | 不匹配 query，避免 `redirectPath=/website-login/captcha` 把登录页误判成验证页 | 代码明确实现 + **注释声称** |
| `EscapedPath` | `url.Path` 会把 `%2F` 解码成 `/`，与 JS `location.pathname` 不一致；用 `EscapedPath` 保持编码形式 | 代码明确实现 + **注释声称** |
| 读地址 | CDP `proto.PageGetFrameTree{}` + `page.Timeout(3s)`；不注入 JS | 代码明确实现 |
| 为何不用 `page.Info()` | 注释：`Info()` 走 browser session，不受 `page.Timeout` 约束，页面取消后仍会再发一次 CDP 调用 | **注释声称** |
| 失败语义 | 解析失败/读取失败/取不到 frame → 返回 `nil`（不拦截） | 代码明确实现 |
| **调用点** | 仅 `xiaohongshu/search.go:131`、`:193`、`search_ready.go:172`；**发布链路不调用** | 代码明确实现 |

发布链路的风控/登录态处理因此只有：`ensureCreatorSession()`（cookie `galaxy_creator_session_id`，15s 等待）与 `waitPublishSuccess` 的「未跳转即失败」。**代码明确实现**。

## 7. Humanize

`humanize/` 全部为 LogNormal：`secs = exp(Mu + Sigma*z)`，`z = rand.NormFloat64()`，落在 `[Min, Max]` 区间内截断（先判 `Max` 再转 `Duration`，避免溢出）。

| Action | Mu | Sigma | Min | Max | 发布链路是否使用 |
|---|---|---|---|---|---|
| `Keystroke` | -2.12 | 0.50 | 30ms | 400ms | 是（`Type` 每 rune） |
| `AfterType` | -0.51 | 0.40 | 200ms | 3s | 是（标题后 ×2、正文+标签后 ×1） |
| `AfterNavigate` | 0.41 | 0.45 | 600ms | 6s | 仅 `ensureCreatorSession` 建档成功时 |
| `BeforeSubmit` | 0.0 | 0.40 | 400ms | 4s | **否**（仅 `notification_reply.go:82`） |
| `PointerSettle` | -1.20 | 0.35 | 200ms | 1200ms | 是（`Click` 内，移动后按下前） |
| `ClickHold` | -2.47 | 0.33 | 45ms | 250ms | 是（按下与抬起之间） |

其余：`AfterClick`(-0.92/0.35, 150ms–2s)、`BeforeClick`(-1.61/0.45, 80ms–1s)、`BetweenScroll`(-0.22/0.40, 250ms–3s)、`Reading`(-0.36/0.40, 300ms–3s)、`AfterInteract`(0.88/0.30, 2s–3s)。均为 **代码明确实现**（`humanize/provider.go`）。

- `Type()`(input.go:247)：`Focus` → `WaitEnabled` → `WaitWritable` → 逐 rune `page.InsertText(string(r))` → 睡一个 `Keystroke` 样本，`ctx` 可中断。**代码明确实现**。
- `page.InsertText` 即 CDP `Input.insertText`（rod 注释「like pasting text into the page」），**不产生 keydown/keyup/char 事件**。**代码明确实现（依赖库实现，rod `input.go`）**。
- `Click()`(107)：`WaitInteractable` → 抖动落点 → 视口 + 有效不透明度检查 → 曲线移动 → `Delay(PointerSettle)` → `WaitEnabled` → `stillOn` 复核（±1px 容差 + 可见）→ 按下 → 睡 `ClickHold` → 抬起。**代码明确实现**。
- 抖动：`limit = min(|宽或高| * 0.15, 8)`，偏移 `(rand-0.5)*2*limit`，X/Y 各一次。**代码明确实现**。
- 曲线：距离 <6px 直连；`steps = clamp(round(dist/10), 10, 40)`；控制点沿法线偏移 `dist*(0.05+rand*0.10)`、符号随机；每步 `5+rand.Intn(5)` ms；三次贝塞尔 + `easeInOut(t)`（前半 `2t²`，后半 `1-(-2t+2)²/2`）。**代码明确实现**。
- 可见性判据：元素及各级祖先 `opacity` 连乘 `>= 0.1`，链上任一 `display:none` / `visibility:hidden` 记 0；读不到样式按可见。**代码明确实现**。
- 发布链路里没有 `BeforeSubmit` 级别的「提交前停顿」，点发布前只有 `Click` 内部的 `PointerSettle` + `ClickHold`。**代码明确实现**。

## 8. 标题长度

`pkg/xhsutil/title.go` `CalcTitleLength()`(7)；校验点 `service.go` `PublishContent()`(206) 行 208 `> 20` 即拒绝。

- 先 `utf16.Encode([]rune(s))`，再对每个 UTF-16 code unit 计：`>127` 记 2，否则记 1；返回 `(byteLen+1)/2`（向上取整）。**代码明确实现**。
- 注释称「非 ASCII 算 2 字节、ASCII 算 1 字节，最终向上取整除以 2」。**注释声称**。
- 推论：中文每字 2 单位 → 计 1，上限 20 字；ASCII 每字符 1 → 计 0.5，上限 40 字符；代理对（emoji）为 2 code unit → 计 2。**代码明确实现（公式直接推论）**。

## 9. 正文长度

- `checkTitleMaxLength()`(633)：在标题输入 + `AfterType` 之后立刻 `page.Has("div.title-container div.max_suffix")`。**代码明确实现**。
- `checkContentMaxLength()`(651)：在正文、`tryRefocusTitle`、标签、`AfterType` 之后 `page.Has("div.edit-container div.length-error")`。**代码明确实现**。
- 两者语义相同：元素**存在**即失败（`page.Has` 只判节点是否存在，不判可见性），文案按 `/` 拆成「当前/上限」，拆不出就整串报错；元素不存在即通过。**代码明确实现**。
- 即：不读计数器数值做比较，只读「越限提示节点是否存在」。**代码明确实现**。

## 10. 选择器清单（发布 happy path）

| 环节 | 选择器/属性 | 中文依赖 | 位置 |
|---|---|---|---|
| 发布页就绪 | `div.upload-content` | 无 | publish.go:157 |
| 切 TAB | `div.creator-tab` + 文本 `上传图文`/`上传视频` | **主定位** | publish.go:156/200 |
| 图片上传框 | `.upload-input`、`input[type="file"]` + `accept` | 无 | publish.go:283 |
| 图片预览计数 | `.img-preview-area .pr` | 无 | publish.go:332 |
| 标题框 | `div.d-input input` | 无 | publish.go:355 |
| 标题越限 | `div.title-container div.max_suffix` | 无 | publish.go:634 |
| 正文框 | `div[role="textbox"][contenteditable="true"]`、`div.tiptap[contenteditable="true"]`、`div.ql-editor` | 无 | publish.go:680 |
| 正文兜底 | `p[data-placeholder]` 含 `输入正文描述` → 上溯 `role=textbox` | **内层过滤**（仅兜底） | publish.go:913 |
| 话题联想 | `#creator-editor-topic-container .item` → `.name` | 无 | publish.go:868 |
| 话题回读 | `a[data-topic]` + JSON `name` | 无 | publish.go:789 |
| 引导卡 | `.feature-guide__btn` | 无 | publish.go:598 |
| 浮层 | `div.d-popover` | 无 | publish.go:112 |
| 可见范围 | `div.permission-card-wrapper div.d-select-content`；选项 `div.d-options-wrapper div.d-grid-item div.custom-option` + 文本含可见范围值 | **内层过滤**（值本身是中文入参） | publish.go:1023/1034 |
| 定时开关 | `.post-time-wrapper .d-switch` | 无 | publish.go:1083 |
| 日期输入 | `.date-picker-container input`（`SelectAllText` + 输入 `2006-01-02 15:04`） | 无 | publish.go:1100 |
| 原创卡片 | `div.custom-switch-card` + 文本含 `原创声明`；内层 `div.d-switch`、`input[type=checkbox].checked` | **内层过滤** | publish.go:1119/1121 |
| 原创弹窗 | `div.footer` + 文本含 `原创声明须知` / `声明原创`；`div.d-checkbox`、`button.custom-button` | **内层过滤** | publish.go:1182 |
| 商品按钮 | `span.d-text` + 文本 `添加商品`，上溯 `button`/含 `d-button` | **内层过滤** | publish.go:1326 |
| 商品搜索框 | `input[placeholder="搜索商品ID 或 商品名称"]` | **主定位** | publish.go:1407 |
| 商品弹窗 | `.multi-goods-selector-modal`、`.goods-list-loading`、`.goods-list-normal .good-card-container .d-checkbox`、`.goods-selected-footer button` | 无 | publish.go:1388 起 |
| 发布按钮（新） | `xhs-publish-btn` + `is-publish` + `submit-disabled` | 无 | publish.go:490 |
| 发布按钮（旧） | `.publish-page-publish-btn button.bg-red` + `disabled`/`aria-disabled`/`class` | 无 | publish.go:520 |
| 登录态 | `.main-container .user .link-wrapper .channel` | 无 | login.go |
| 扫码图 | `.login-container .qrcode-img[src]` | 无 | login.go |
| 创作者会话 | cookie `galaxy_creator_session_id` | 无 | creator_session.go:19 |
| 风控页 | 路径前缀 `/website-login/captcha`、`/website-login` | 无（纯路径） | page_check.go:29 |

## 11. 浏览器启动与 stealth

`browser/browser.go` `NewBrowser()`(50)；`headless_browser.go` `New()`。

- `EnsureBrowser()` 失败即 `panic("内置浏览器不可用，拒绝启动")`；注释说明不用 rod 自下载的默认 Chromium（不认识指纹 flag 会静默降级）。**代码明确实现 + 注释声称**。
- 二进制按 `browser_version.txt` 从 `https://cdn.one-world.ai/browsers/<ver>/` 下载，SHA256 校验（下载 `SHA256SUMS`），平台 `macos-arm64.dmg` / `linux-x64.tar.xz` / `windows-x64.zip`；缓存到 `os.UserCacheDir()/xiaohongshu-mcp/browser/<ver>`。**代码明确实现**。
- 选项：`WithHeadless(headless)`；`WithFingerprint("")`（空 = 按 OS：darwin→`macos`，其余→`windows`）；**`WithStealthJS(false)`**；`WithLanguage("zh-CN")`；`WithExtraFlags({"fingerprint-brand":"Chrome"})`；`WithChromeBinPath(binPath)`；可选 `WithProxy` / `WithFingerprintSeed`（>0 才下发）；cookie 从 `cookies.json` 载入（路径优先级 `COOKIES_PATH` → 本地 → 旧 `/tmp`）。**代码明确实现**。
- 启动 flag：`--no-sandbox`、`--fingerprint=<seed>`、`--fingerprint-platform=<platform>`、额外 flag 透传；seed 为 0 时 `rand.Intn(89999)+10000`。**代码明确实现**。
- `stealthJS=false` → 新页面用 `browser.MustPage()`，不注入 go-rod/stealth JS（注释：源码级补丁已处理，再注入反而矛盾）。**代码明确实现 + 注释声称**。
- UA：不设 `--user-agent`；改为每页 `Network.setUserAgentOverride`，UA 取 `Browser.getVersion` 实读串，brands 为 `Not:A-Brand 99` / `Google Chrome <major>` / `Chromium <major>`，`fullVersionList` 用完整版本，`AcceptLanguage = "zh-CN,zh"`（避免带 q 值污染 `navigator.languages`）；平台字段留空交给 CloakBrowser 补丁。**代码明确实现 + 注释声称**。
- 代理：`l.Proxy(cfg.Proxy)`；注释说明 Chrome `--proxy-server` 不支持内嵌凭据。日志中用户名/密码打码。**代码明确实现 + 注释声称**。
- 定时发布范围（`service.go` 206/290）：ISO8601 解析，`now+1h` 至 `now+14d`，越界直接报错。**代码明确实现**。
- 标签上限：`Publish()` 内 `len(tags) >= 10` 截前 10。**代码明确实现**。

## Answer

供 05（选择器基线）直接引用的矩阵雏形：

| 环节 | 选择器或属性 | 中文依赖(无/内层/主定位) | 源码位置 | 置信度 |
|---|---|---|---|---|
| 发布按钮（新） | `xhs-publish-btn` / `is-publish!="false"` / `submit-disabled!="true"` | 无 | publish.go:490 `findPublishButton` | 代码明确实现 |
| 发布按钮（旧） | `.publish-page-publish-btn button.bg-red` / `disabled` 存在 / `aria-disabled=="true"` / class `disabled` | 无 | publish.go:520 | 代码明确实现 |
| 按钮点击 | `ScrollIntoView` + quad 外接矩形 + 65%/50% + `ClickAt` | 无 | publish.go:554 `clickPublishWidget` | 代码明确实现 |
| 成功判定 | URL 不含 `/publish/publish`，15s / 500ms | 无 | publish.go:425 `waitPublishSuccess` | 代码明确实现 |
| 话题联想 | `#creator-editor-topic-container .item` `.name`，5s/200ms/3 次 | 无 | publish.go:831/867 | 代码明确实现 |
| 话题回读 | `a[data-topic]`，数量 +1，JSON `name` EqualFold，1s | 无 | publish.go:789 `verifyInsertedTopic` | 代码明确实现 |
| 图片完成 | `.img-preview-area .pr` 计数 `>=i+1`，60s/500ms | 无 | publish.go:325 `waitForUploadComplete` | 代码明确实现 |
| 视频就绪 | 发布按钮可点击，10min 窗口（page deadline 5min） | 无 | publish_video.go:79 `uploadVideo` | 代码明确实现 / 先到者仅推断 |
| 风控页 | 路径 `/website-login/captcha`、`/website-login`，`EscapedPath`，CDP `Page.getFrameTree` | 无 | page_check.go:29/43/55 | 代码明确实现（发布链路未调用） |
| 标题长度 | `utf16` code unit >127 记 2，`(n+1)/2`，上限 20 | 无 | pkg/xhsutil/title.go:7；service.go:208 | 代码明确实现 |
| 标题/正文越限 | `div.title-container div.max_suffix` / `div.edit-container div.length-error` 存在即失败 | 无 | publish.go:633/651 | 代码明确实现 |
| 切 TAB | `div.creator-tab` + 文本 `上传图文`/`上传视频` | **主定位** | publish.go:156/200 | 代码明确实现 |
| 打字节奏 | `InsertText` 逐 rune + `Keystroke` 30–400ms（LogNormal -2.12/0.50） | 无 | humanize/input.go:247/266 | 代码明确实现 |
| 点击节奏 | `PointerSettle` 200–1200ms + `ClickHold` 45–250ms | 无 | humanize/input.go:16/123 | 代码明确实现 |
| 浏览器 | `--fingerprint`/`--fingerprint-platform`/`--fingerprint-brand=Chrome`、`StealthJS(false)`、UA 覆盖、`zh-CN` | 无 | browser/browser.go:50；headless_browser.go `New` | 代码明确实现 |

其余选择器（正文框/兜底、原创、可见范围、商品、登录态）逐条见 §10，可直接并入本表。
