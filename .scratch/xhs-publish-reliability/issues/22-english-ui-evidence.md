# 22 — 英文界面文案与选择器取证

Status: resolved
Type: task
Blocked by: —
Assignee: wayfinder-session (opencode)

## Question

05 定了「文本兜底中英双语、英文优先中文」，但 02 的真机取证全程是中文界面，英文文案目前**没有任何证据**。本票确认：

1. **英文界面是否真实存在**：小红书创作后台在 `en-US`（browser locale / Profile 语言 / `Accept-Language: en-US`）下是否真的渲染英文？还是服务端固定中文？
2. 若存在，逐项抓取英文文案，产出「中文文案 × 英文文案 × 所在容器」对照表，覆盖：
   - 标题 placeholder；
   - 正文 placeholder；
   - 原创声明开关文案、原创确认弹窗正文/「声明原创」按钮；
   - 「添加内容类型声明」入口与下拉选项（虚构演绎/笔记含AI合成内容/内容包含营销广告/内容来源声明/自主拍摄/来源转载）；
   - 封面弹窗（设置封面/上传封面/确定）；
   - 登录页（APP扫一扫登录/登录二维码）。
3. 若不存在：明确记录「无英文界面」的证据（同一 URL、同一节点、中文文案不变），供 17 删除全部英文兜底分支。

方法与 02 相同（复用 `research/capture_live_dom.py` / `probe_editor_controls.py`，用 `cookies/xiaohongshu_180.json` 的有效登录态，**全程不发布**）。托管模式 Profile 若可改语言，另记一条托管侧结果。

## Answer

**英文界面不存在。** 结论落盘：`research/22-english-ui-evidence.md`。

取证方式：同一账号（`cookies/xiaohongshu_180.json`）、同一 URL、同一操作，只改浏览器语言上下文——`zh-CN` 基线 vs `en-US`（`locale=en-US` + `Accept-Language: en-US,en;q=0.9`）。脚本 `research/22_english_ui_probe.py`、`research/22_english_ui_cover_login.py`，**全程未发布**。原始快照 `research/raw/22-*`。

### 三条决定

1. **语言上下文确实生效**：en-US 上下文里 `navigator.language=en-US`、`navigator.languages=["en-US"]`、`Intl` locale `en-US`。
2. **界面文案一个字都没变**：图文编辑器上传同一张图后，`document.body.innerText` 归一化后的 sha256 前 16 位在 zh-CN 与 en-US 下**完全相同**（`b6ae877c90c8b978`）；`22-report.json` 的 diff 只有 `navLang`/`navLangs` 两项，无任何文案差异。`<html>` 无 `lang`、全页 0 个 `[lang]` 节点、页面 HTML 不含 `i18n`/`locale` 字样、响应头无 `Content-Language`。
3. **逐项文案（en-US 下实测）全为中文**：标题 placeholder `填写标题会有更多赞哦`；正文 `输入正文描述，真诚有价值的分享予人温暖`；原创开关 `原创声明` + 弹窗正文与 `声明原创` 按钮；声明入口 `添加内容类型声明` + 顶层四项（`虚构演绎，仅供娱乐`/`笔记含AI合成内容`/`内容包含营销广告`/`内容来源声明`）+ 来源二级（`自主拍摄`/`来源转载`）；封面弹窗 `设置封面`…`上传`/`完成`；登录页默认 `短信登录`…，切二维码后 `APP扫一扫登录`/`扫码即同意`；二维码图为 `img.css-1lhmg90`（`data:image/png`），切换图标为 `img.css-wemwzq`。

### 对下游的直接含义

- **17**：规格里**所有 `en` / `text-en` 文案兜底分支删除**；文本兜底只保留中文，且仍排在结构主分支之后。05 的「中英双语、英文优先中文」不再成立。
- **05**：英文词表不用回填，直接删；「文本兜底至少验证一次目标语言界面」的删除条件**已满足**（本次即目标语言界面验证）→ 标题/正文的结构主分支稳定命中后即可删中英文本兜底。登录二维码行（第 14 行）可落在实机：`.login-box-container` 内切换图标 `img.css-wemwzq`、二维码 `img.css-1lhmg90`，无需文案。
- **07**：无英文界面 → 登录/验证判定继续纯 path + `login-box`，不受影响；本次**仍未观察到** `/website-login*`（与 02 一致），未补到 07 §8 所需的验证码正样本。
- **顺带发现（已记入 05 评论）**：封面入口已漂移——现网**没有** `div.upload-cover` / `.cover-plugin-preview div.default.pointer`，结构入口是 `.cover-edit-entry`；封面弹窗是 `.d-modal.cover-modal.creator-modal-style.main-cover-editor-modal`，按钮为 `上传`/`完成`，没有「上传封面」tab 与「确定」。

### 未覆盖

托管模式 Profile 语言（未改 Profile 语言，标**需真机验证**；但后台无语言切换入口、无 i18n，托管侧出英文仅理论可能）；有头模式；验证码页形态。

## Comments

- 来自 **07**（2026-11-11）：登录/验证判定**不依赖任何文案**（纯主框架 path + 结构节点 `login-box`），因此本票**无需**为登录/验证页取证英文文案。若本票顺带拍到 `/website-login*` 或验证码页，请把 step URL 与 DOM 摘录补进 07 §8 的两条真机缺口（该路径是否会出现、正常发布页上 login-box 的可见性）。
