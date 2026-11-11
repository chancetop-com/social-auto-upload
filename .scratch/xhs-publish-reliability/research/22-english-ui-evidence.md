# 22 — 英文界面取证（发布页 / 图文编辑器 / 视频封面 / 登录页）

- 取证时间：2026-11-11（本机，headless Chromium 156.0.8078.4，patchright）
- 账号：`cookies/xiaohongshu_180.json`（登录态有效），**全程未发布**；上传的图片/视频仅进入编辑器，未提交
- 对照方式：同一账号、同一 URL、同一套操作，只改浏览器语言上下文
  - `zh-CN` 基线：`locale=zh-CN`、`Accept-Language: zh-CN,zh;q=0.9`（本地模式现状）
  - `en-US` 测试：`locale=en-US`、`Accept-Language: en-US,en;q=0.9`
  - 两者共享：`channel="chromium"`、stealth init script、UA 去掉 `HeadlessChrome`
- 脚本：`research/22_english_ui_probe.py`（zh/en 对照矩阵）、`research/22_english_ui_cover_login.py`（封面弹窗 + 登录二维码面板）
- 原始数据（本地，未脱敏，勿入 git）：`research/raw/22-*.json|png|txt`、汇总 `raw/22-report.json`、`raw/22-report-extra.json`
- 置信度口径：**真机取证** = 本次实际观察到；**仅推断** = 无本次证据

## 0. 结论

**英文界面不存在。** 在 `locale=en-US` + `Accept-Language: en-US` 下（`navigator.language` 实测为 `en-US`、`navigator.languages` 为 `["en-US"]`），创作后台所有已采环节**仍渲染原中文文案**，与 `zh-CN` 基线逐字相同：

- 图文编辑器 `document.body.innerText` 归一化后 **sha256 前 16 位完全一致**（`b6ae877c90c8b978`）；`22-report.json` 的 `diff` 只有 `navLang` / `navLangs` 两项（语言上下文本身），**没有任何文案差异**。
- `<html>` **没有 `lang` 属性**；全页 **0 个 `[lang]` 节点**；`document.documentElement.outerHTML` 中 **不含 `i18n` / `locale` 字样**。
- 文档响应头只有 `content-type`，**没有 `Content-Language`**。

→ 17 的规格里**所有 `en` / `text-en` 兜底分支都应删除**；05 的「文本兜底中英双语、英文优先中文」收敛为「中文单语兜底，且仍排在结构主分支之后」。

> 边界：以上为**本地模式**（浏览器 locale + `Accept-Language`）真机结论。托管模式的界面语言由 Profile 决定，本次未改 Profile 语言，属**未覆盖**；但后台没有任何语言切换入口、无 `lang`、无 i18n 文案表，服务端也不回 `Content-Language`，托管侧出现英文界面**仅存在理论可能**（见 §5）。

## 1. 文案对照表（en-US 实测）

> 「英文文案」一列的值是本次 **en-US 上下文里实际渲染的文本**。全部为中文 → 该环节没有英文变体。

| # | 环节 | 结构锚点 / 容器 | 中文文案（zh-CN 基线） | en-US 实际渲染 | 结论 |
|---|---|---|---|---|---|
| 1 | 标题 placeholder | `div.d-input input.d-text` | `填写标题会有更多赞哦` | `填写标题会有更多赞哦`（同节点、同 placeholder） | 无英文 |
| 2 | 正文 placeholder | `div.tiptap p[data-placeholder]` | `输入正文描述，真诚有价值的分享予人温暖` | 同左（`data-placeholder` 未变） | 无英文 |
| 3 | 原创声明开关 | `.custom-switch-card`（按顺序：原创声明 / 允许正文复制 / 定时发布） | `原创声明` | `原创声明` | 无英文 |
| 4 | 原创确认弹窗 | `.d-modal.d-modal-centered.creator-modal-style` | `笔记完成原创声明后，将获得以下权益 1. 获得原创笔记标记 2. 平台保护你的作品，识别并打击搬运 我已阅读并同意 《原创声明须知》 ，如滥用声明，平台将驳回并予以相关处置 声明原创` | 同左（弹窗正文 + 按钮 `声明原创` 全中文） | 无英文 |
| 5 | 内容类型声明入口 | `.d-select` 内 `.d-select-placeholder` | `添加内容类型声明` | `添加内容类型声明` | 无英文 |
| 6 | 声明下拉（顶层） | `.d-popover.declaration-drop-down` | `虚构演绎，仅供娱乐` / `笔记含AI合成内容` / `内容包含营销广告` / `内容来源声明` | 同左，四项全中文 | 无英文 |
| 7 | 声明二级（来源） | `.d-popover`（第二个） | `自主拍摄` / `来源转载` | 同左，两项全中文 | 无英文 |
| 8 | 封面弹窗 | 入口 `.cover-edit-entry`（「编辑封面」）→ `.d-modal.cover-modal.creator-modal-style.main-cover-editor-modal` | `设置封面` / `AI修改` / `裁剪` / `模版` / `贴纸` / `文字` / `滤镜` / `生成封面` / `编辑` / `预览` / `上传` / `获取封面建议` / `完成` | 同左，全部中文 | 无英文 |
| 9 | 登录页默认 tab | `div[class*="login-box"]` | `短信登录` / `发送验证码` / `收不到验证码？` / `登 录` / `登录即同意` / `用户协议` / `隐私政策` | 同左 | 无英文 |
| 10 | 登录二维码面板 | 同上，点 `img.css-wemwzq` 后 | `APP扫一扫登录` / `扫码即同意` / `用户协议` / `隐私政策` | 同左 | 无英文 |

补充（同一页面上的其它可见中文，均随 en-US 上下文不变）：`发布笔记`、`图片编辑`、`获取封面建议`、`智能标题`、`笔记预览`、`封面预览`、`内容设置`、`公开可见`、`定时发布`、`我知道了`。

## 2. 「语言上下文确实生效」的核验

抓取时同步记录浏览器侧语言（`22-report.json` → `locales.*.image.base`）：

| 上下文 | `navigator.language` | `navigator.languages` | `Intl.DateTimeFormat().locale` |
|---|---|---|---|
| zh-CN | `zh-CN` | `["zh-CN"]` | `zh-CN` |
| en-US | `en-US` | `["en-US"]` | `en-US` |

→ en-US 上下文**不是没生效**：浏览器语言确为英文，但界面仍是中文。排除「locale 没设上」导致假阴性。

## 3. 图文编辑器整体文案指纹

同一操作序列（上传 1 张图片 → 等编辑器就绪）：

| 上下文 | `bodyText` sha256 前 16 位 | 说明 |
|---|---|---|
| zh-CN | `b6ae877c90c8b978` | 基线 |
| en-US | `b6ae877c90c8b978` | **逐字相同** |

`22-report.json` 的 `diff` 只包含：

```json
{"navLang": {"zh-CN": "zh-CN", "en-US": "en-US"},
 "navLangs": {"zh-CN": ["zh-CN"], "en-US": ["en-US"]}}
```

视频页 `bodyText` 两次不完全相同，但差异只有**动态推荐话题**（`#绿幕素材 #原创视频 …` 时有时无）与上传文件名/时长等运行时文本，**没有任何语言差异**；视频封面弹窗的 `bodyText` 两次 **完全一致**（657 字符）。

## 4. 登录页（en-US，无会话）

| 项 | 结果 |
|---|---|
| 落地 URL | `https://creator.xiaohongshu.com/login?source=&redirectReason=401&lastUrl=…`（HTTP 200） |
| `login-box` | 1 个、可见 |
| 默认面板文案 | `短信登录 | 发送验证码 | 收不到验证码？ | 登 录 | 登录即同意 | 用户协议 | 和 | 隐私政策` |
| 切二维码的结构锚点 | `div[class*="login-box"] img.css-wemwzq`（`src` 为 `data:image/png;base64,…`） |
| 二维码面板文案 | `APP扫一扫登录 | 扫码即同意 | 用户协议 | 和 | 隐私政策` |
| 二维码图片 | `img.css-1lhmg90`，`src` 为 `data:image/png;base64,…` |
| 是否出现 `/website-login*` | **未出现**（与 02 的观察一致） |

→ 07 的「登录判定不依赖文案」结论不受影响；本项也未给 07 §8 补到 `/website-login*` 或验证码页的正样本。

## 5. 未覆盖 / 需真机验证

- **托管模式（Multilogin / AdsPower）的 Profile 语言**：托管分支忽略 `locale` / `extra_http_headers`（`utils/browser_session.py`），界面语言由 Profile 决定。本次未改 Profile 语言，故托管侧**没有直接证据**，标 **需真机验证**；但后台无语言切换入口、无 `lang`、无 i18n 文案表，服务端也不回 `Content-Language`，英文界面**仅存在理论可能**。
- 未主动触发验证码页，`/website-login/captcha` 形态仍空（归 07 §8）。
- 未覆盖「有头模式」；与 02 同口径（本地无头 + 相同 launch/context 参数）。

## 6. 顺带发现（不影响本票结论，供 05 / 17 修订）

1. **封面入口已漂移**：现网视频页 **没有** `div.upload-cover`，也**没有** `.cover-plugin-preview div.default.pointer`；`div.upload-cover` 的 `click()` 直接 30s 超时。当前可用结构入口是 **`.cover-edit-entry`**（其容器为 `.cover-edit-stack`，文案「编辑封面」）。
2. **封面弹窗结构已变**：弹窗为 `.d-modal.cover-modal.creator-modal-style.main-cover-editor-modal`，内部按钮是 **`上传` / `完成`**，**没有** 05 矩阵里假设的「上传封面」tab 与「确定」按钮。05 第 13 行的候选与失败文案需按此更新。
3. **发布按钮的可见「发布」字样不在 light DOM**：`xhs-publish-btn` 的 `textContent` / `innerText` 均为空、无 `shadowRoot`，但截图里按钮可见中文「发布」；因此 `button:has-text("发布")` 仍为 0 命中（与 02 一致）。文案来源**未定位**（仅推断为内部子组件/伪元素），不影响零文本基线。

## 7. 原始证据索引

| 文件 | 内容 |
|---|---|
| `raw/22-report.json` | zh/en 对照矩阵（编辑器控件、声明、原创弹窗、视频、封面、登录、文本指纹与 diff） |
| `raw/22-report-extra.json` | 首轮补采（封面点击失败、登录默认面板） |
| `raw/22-en-US-image-editor.json` / `.png` | en-US 图文编辑器基础控件与截图 |
| `raw/22-en-US-image-original-modal.json` / `.png` | en-US 原创确认弹窗 |
| `raw/22-en-US-declaration-menu.json` / `.png` | en-US 声明下拉顶层四项 |
| `raw/22-en-US-declaration-source.json` / `.png` | en-US 来源声明二级两项 |
| `raw/22-en-US-video-video.json` / `.png` | en-US 视频编辑器 |
| `raw/22-en-US-cover-modal.json` / `.txt` / `.png` | en-US 封面弹窗（新结构） |
| `raw/22-login-en-US.json` / `.png` | en-US 登录页默认（短信）面板 |
| `raw/22-en-US-login-qr.json` / `.png` | en-US 登录二维码面板 |
| `raw/22-zh-CN-*` | 同操作的 zh-CN 基线快照 |
